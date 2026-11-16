"""Claude: writes a lesson as a storyboard, and edits one through small tools.

Two jobs, and both are things only a model can do: turn a topic (and someone's notes)
into a lesson that teaches, and turn "make scene 3 simpler" into concrete changes.
Everything Claude returns is validated against the storyboard schema before it's kept.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

import anthropic
from pydantic import ValidationError

from collections.abc import Callable

from app import github, grounding
from app.storyboard import LAYOUTS, MAX_ITEMS, MAX_SCENES, Scene, Storyboard, next_scene_id, normalize, strict_json_schema

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AIError(Exception):
    """A failure the page can explain in one sentence."""

    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        # requests already paid for before the failure, so they can be logged and counted
        self.calls: list[Call] = []


@dataclass
class Call:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    ms: int = 0


def model() -> str:
    return os.environ.get("CLAUDE_MODEL") or "claude-opus-5-5"


def client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise AIError("ai_not_configured", "AI writing isn't set up on this server yet, so Claude can't write or edit lessons.", 503)
    return anthropic.Anthropic(api_key=key, timeout=240.0, max_retries=1)


def _call(**kwargs: Any) -> tuple[Any, Call]:
    """One request to Claude, with every failure turned into a sentence."""
    started = time.monotonic()
    try:
        resp = client().beta.messages.create(
            model=model(),
            betas=[FALLBACK_BETA],
            fallbacks="default",
            cache_control={"type": "ephemeral"},  # tool loops resend the same prefix every turn
            **kwargs,
        )
    except AIError:
        raise
    except anthropic.AuthenticationError as exc:
        raise AIError("ai_key_invalid", "The server's Claude key was refused. The lesson can't be written until it's fixed.", 503) from exc
    except anthropic.RateLimitError as exc:
        raise AIError("ai_busy", "Claude is getting too many requests right now. Wait a minute and try again.", 429) from exc
    except anthropic.APITimeoutError as exc:
        raise AIError("ai_timeout", "Claude took too long to answer. Try again; a shorter lesson is quicker.", 504) from exc
    except anthropic.APIConnectionError as exc:
        raise AIError("ai_unreachable", "The server couldn't reach Claude. Try again in a moment.", 502) from exc
    except anthropic.APIStatusError as exc:
        if exc.status_code >= 500:
            raise AIError("ai_down", "Claude is having trouble right now. Try again in a minute.", 502) from exc
        raise AIError("ai_rejected", f"Claude couldn't take this request ({exc.status_code}).", 502) from exc

    call = Call(
        model=getattr(resp, "model", None) or model(),
        input_tokens=resp.usage.input_tokens or 0,
        output_tokens=resp.usage.output_tokens or 0,
        ms=int((time.monotonic() - started) * 1000),
    )
    if resp.stop_reason in ("refusal", "max_tokens"):
        err = (
            AIError("ai_refused", "Claude declined to write this. Try rewording the topic.", 422)
            if resp.stop_reason == "refusal"
            else AIError("ai_too_long", "The lesson came out too long to finish. Try a shorter length.", 502)
        )
        err.calls = [call]
        raise err
    return resp, call


# ---------------------------------------------------------------- writing a lesson

LEVELS = {
    "intro": "a curious beginner who has never studied this: no jargon without a plain explanation, one idea at a time",
    "intermediate": "a college student who has taken an intro course: name the real terms, skip the very basics",
    "advanced": "someone who knows the field and wants precision: exact terms, the subtle parts, no hand-holding",
}

LAYOUT_GUIDE = "\n".join(f"- {name}: {desc}" for name, desc in LAYOUTS.items())

WRITE_SYSTEM = f"""You write short narrated video lessons. A lesson is a storyboard: a list of scenes,
each a slide with a little text on screen and narration spoken over it.

How a good lesson works:
- Open with a title scene that says why the topic matters, then build the idea one step at a
  time, show it working on a concrete example, and end with a summary scene of the takeaways.
- The narration teaches; the screen only anchors it. On-screen text is short (a few words per
  item). Never put the narration on screen.
- Narration is written for the ear: short sentences, plain words, no parentheses, no lists read
  aloud as "first, second" unless they're on screen as steps. Write numbers, symbols and
  formulas the way a person says them ("w minus the learning rate times the gradient").
- Each item appears while its sentence is spoken: set `at` to the index of the narration
  sentence (counting from 0) that introduces it. Sentences end with . ! or ?
- Every scene id is s1, s2, s3... in order.
- Be correct. If you aren't sure of a fact, leave it out rather than guess.

Layouts:
{LAYOUT_GUIDE}

Limits: at most {MAX_SCENES} scenes, at most {MAX_ITEMS} items a scene, at most 14 lines of code."""


def _write_prompt(topic: str, notes: str, level: str, minutes: int) -> str:
    words = minutes * 150
    scenes = max(4, min(MAX_SCENES, round(minutes * 2.3) + 1))
    parts = [
        f"Topic: {topic}",
        f"Audience: {LEVELS.get(level, LEVELS['intro'])}.",
        f"Length: about {minutes} minutes spoken, so about {words} words of narration in total, over about {scenes} scenes.",
    ]
    if notes:
        parts.append(
            "The learner pasted their own notes below. Teach what the notes teach, in the notes' terms and "
            "notation, so the lesson matches their course. Don't contradict the notes. If the notes leave a gap "
            "you need to fill, keep it brief.\n\n<notes>\n" + notes + "\n</notes>"
        )
    return "\n\n".join(parts)


def write_storyboard(topic: str, notes: str, level: str, minutes: int) -> tuple[Storyboard, Call]:
    resp, call = _call(
        max_tokens=16000,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": strict_json_schema(Storyboard)}},
        system=WRITE_SYSTEM,
        messages=[{"role": "user", "content": _write_prompt(topic, notes, level, minutes)}],
    )
    text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
    try:
        board = Storyboard.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        err = AIError("ai_bad_output", "Claude's lesson didn't come out in a shape the editor can use. Try again.", 502)
        err.calls = [call]
        raise err from exc
    return normalize(board), call


# ---------------------------------------------------------------- editing a lesson

_scene_body = strict_json_schema(Scene)
_scene_body["properties"].pop("id")
_scene_body["required"].remove("id")

EDIT_TOOLS = [
    {
        "name": "update_scene",
        "description": "Replace one scene's content (layout, text on screen, narration). Send the whole scene as it should end up, including the parts you aren't changing.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "scene_id": {"type": "string"},
                "scene": _scene_body,
                "note": {"type": "string", "description": "Half a sentence on what changed, for the person, e.g. 'shorter narration, simpler words'."},
            },
            "required": ["scene_id", "scene", "note"],
            "additionalProperties": False,
        },
    },
    {
        "name": "insert_scene",
        "description": "Add a new scene after an existing one. Use after_scene_id \"\" to put it first.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "after_scene_id": {"type": "string"},
                "scene": _scene_body,
                "note": {"type": "string"},
            },
            "required": ["after_scene_id", "scene", "note"],
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_scene",
        "description": "Remove a scene.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"scene_id": {"type": "string"}, "note": {"type": "string"}},
            "required": ["scene_id", "note"],
            "additionalProperties": False,
        },
    },
    {
        "name": "move_scene",
        "description": "Move a scene so it comes right after another one. Use after_scene_id \"\" to make it first.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"scene_id": {"type": "string"}, "after_scene_id": {"type": "string"}, "note": {"type": "string"}},
            "required": ["scene_id", "after_scene_id", "note"],
            "additionalProperties": False,
        },
    },
]

EDIT_SYSTEM = f"""You edit a short narrated video lesson for the person who made it. The lesson is a
storyboard of scenes (JSON below). Change it only through the tools: update_scene,
insert_scene, delete_scene, move_scene. Make the smallest set of changes that does what
the person asked, and leave everything else exactly as it is: an untouched scene keeps its
narration word for word, because changed narration has to be voiced again.

When you're done, reply with one or two plain sentences saying what you changed. If the
request can't be done, or would make the lesson wrong, make no changes and say why.

The same rules as when the lesson was written: narration for the ear, short text on screen,
`at` is the narration sentence (from 0) during which an item appears, be correct.

Layouts:
{LAYOUT_GUIDE}"""


@dataclass
class EditOutcome:
    board: Storyboard
    summary: str
    changes: list[dict[str, str]] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)


def _apply(board: Storyboard, name: str, args: dict[str, Any], changes: list[dict[str, str]]) -> tuple[Storyboard, str]:
    """Run one tool on the storyboard. Returns the new storyboard and what to tell Claude."""
    scenes = list(board.scenes)
    ids = [s.id for s in scenes]
    note = str(args.get("note", "")).strip()

    def find(sid: str) -> int:
        if sid not in ids:
            raise ValueError(f"No scene has id {sid!r}. The ids are {', '.join(ids)}.")
        return ids.index(sid)

    if name == "update_scene":
        i = find(args["scene_id"])
        scenes[i] = Scene.model_validate({**args["scene"], "id": args["scene_id"]})
        changes.append({"kind": "updated", "scene_id": args["scene_id"], "note": note})
        result = f"Updated {args['scene_id']}."
    elif name == "insert_scene":
        if len(scenes) >= MAX_SCENES:
            raise ValueError(f"A lesson can have at most {MAX_SCENES} scenes.")
        after = args["after_scene_id"]
        at = 0 if after == "" else find(after) + 1
        new_id = next_scene_id(board)
        scenes.insert(at, Scene.model_validate({**args["scene"], "id": new_id}))
        changes.append({"kind": "inserted", "scene_id": new_id, "note": note})
        result = f"Inserted it as {new_id}."
    elif name == "delete_scene":
        if len(scenes) <= 1:
            raise ValueError("A lesson needs at least one scene.")
        i = find(args["scene_id"])
        scenes.pop(i)
        changes.append({"kind": "deleted", "scene_id": args["scene_id"], "note": note})
        result = f"Deleted {args['scene_id']}."
    elif name == "move_scene":
        i = find(args["scene_id"])
        scene = scenes.pop(i)
        rest = [s.id for s in scenes]
        after = args["after_scene_id"]
        if after != "" and after not in rest:
            raise ValueError(f"No scene has id {after!r}.")
        at = 0 if after == "" else rest.index(after) + 1
        scenes.insert(at, scene)
        changes.append({"kind": "moved", "scene_id": args["scene_id"], "note": note})
        result = f"Moved {args['scene_id']}."
    else:
        raise ValueError(f"There is no tool called {name}.")
    return Storyboard(title=board.title, summary=board.summary, scenes=scenes), result


def edit_storyboard(board: Storyboard, instruction: str, scene_id: str | None, notes: str = "",
                    snap: github.Snapshot | None = None, progress: Progress | None = None) -> EditOutcome:
    focus = ""
    if scene_id:
        idx = next((i for i, s in enumerate(board.scenes) if s.id == scene_id), None)
        if idx is not None:
            focus = f"\n\nThe person is looking at scene {idx + 1} (id {scene_id}). Unless they clearly mean the whole lesson, change only that scene."
    context = f"\n\nTheir notes, which the lesson should stay true to:\n<notes>\n{notes}\n</notes>" if notes else ""
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": f"<storyboard>\n{board.model_dump_json(indent=1)}\n</storyboard>{context}{focus}\n\nWhat they asked: {instruction}",
        }
    ]
    changes: list[dict[str, str]] = []
    calls: list[Call] = []
    current = board

    if snap is not None:
        messages[0]["content"] = f"The lesson teaches github.com/{snap.name}. You can read the code with list_files, read_file and search; cite `source` for any scene you add or change, and leave `code` empty (it's filled from the file).\n\n" + messages[0]["content"]
    try:
        outcome = _edit_loop(current, messages, changes, calls, snap, progress or (lambda _: None))
    except AIError as exc:
        exc.calls = calls + exc.calls  # what was paid for before the failure
        raise
    if snap is not None:
        outcome.board = grounding.ground(outcome.board, snap)
    return outcome


def _edit_loop(current: Storyboard, messages: list[dict[str, Any]], changes: list[dict[str, str]], calls: list[Call],
               snap: github.Snapshot | None = None, progress: Progress = lambda _: None) -> EditOutcome:
    tools = [*READ_TOOLS, *EDIT_TOOLS] if snap is not None else EDIT_TOOLS
    for _ in range(16 if snap is not None else 8):
        resp, call = _call(
            max_tokens=16000,
            output_config={"effort": "medium"},
            system=EDIT_SYSTEM,
            tools=tools,
            messages=messages,
        )
        calls.append(call)
        uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
        if not uses:
            summary = " ".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
            return EditOutcome(normalize(current), summary or "Done.", changes, calls)

        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for use in uses:
            try:
                if snap is not None and use.name in {"list_files", "read_file", "search"}:
                    results.append({"type": "tool_result", "tool_use_id": use.id, "content": _run_read_tool(snap, use.name, dict(use.input), progress)})
                    continue
                current, text = _apply(current, use.name, dict(use.input), changes)
                results.append({"type": "tool_result", "tool_use_id": use.id, "content": text})
            except (ValueError, KeyError, ValidationError) as exc:
                results.append({"type": "tool_result", "tool_use_id": use.id, "content": f"Error: {exc}", "is_error": True})
        messages.append({"role": "user", "content": results})

    raise AIError("ai_loop", "Claude kept going without finishing the edit. Try a simpler request.", 502)


# ---------------------------------------------------------------- teaching a codebase

Progress = Callable[[str], None]

READ_TOOLS = [
    {
        "name": "list_files",
        "description": "List a folder of the repository: its subfolders (with file counts) and files (with line counts). Use \"\" for the top.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_file",
        "description": "Read a file with line numbers. Up to 300 lines a call; use start_line and end_line (0 = to the end) to page through long files.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}},
            "required": ["path", "start_line", "end_line"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search",
        "description": "Search every file (or one folder) for a regular expression or plain text, case-insensitive. Returns path:line: text for each match.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"pattern": {"type": "string"}, "path": {"type": "string", "description": "A folder to search in, or \"\" for all."}},
            "required": ["pattern", "path"],
            "additionalProperties": False,
        },
    },
]

SUBMIT_TOOL = {
    "name": "submit_lesson",
    "description": "Hand in the finished lesson. The server checks every source citation against the repository and tells you what to fix; submit again after fixing.",
    "strict": True,
    "input_schema": strict_json_schema(Storyboard),
}

REPO_SYSTEM = f"""You make short narrated video lessons that teach someone a codebase. The person
pasted a GitHub repository and said what they want to understand. They may have built it with
an AI coding agent and now need to understand, and explain, the code themselves.

Work in two steps.

1. Research with list_files, read_file and search. Start from what you were given (the README
   and the top of the tree), find where the thing they asked about actually happens, and read
   those files: the entry point, the functions involved, how data moves between them. Read
   before you explain. Every statement about the code must come from something you read here,
   never from what projects like this usually do. If the repository doesn't contain what they
   asked about, say so in the lesson instead of guessing.

2. Hand in the lesson with submit_lesson: a storyboard of scenes, each a slide with a little
   text on screen and narration spoken over it.
   - Open with a title scene saying what the repository is and what this lesson covers. End
     with a summary scene. In between, follow the real path through the code, one idea per scene.
   - Show real code with code scenes: set `source` to the file and the 3 to 14 lines that matter.
     Leave `code` empty; the server fills it from the file, so it is always exact. Give each
     item the `line` it explains.
   - Use flow scenes for how pieces connect ("the page calls this route, which calls this
     function"), with the file each piece lives in as the detail.
   - Every scene that explains code cites a source, even when it isn't a code scene. Scenes
     that don't (the title, the summary) have an empty source with lines 0.
   - Narration is for the ear: short sentences, plain words. Don't read code aloud symbol by
     symbol; say what it does, and name files and functions the way a person says them
     ("main dot py", "the save storyboard function").
   - `at` is the index of the narration sentence (counting from 0) during which an item appears.
   - Scene ids are s1, s2, s3... in order.

Layouts:
{LAYOUT_GUIDE}

Limits: at most {MAX_SCENES} scenes, at most {MAX_ITEMS} items a scene."""


def _repo_brief(snap: github.Snapshot) -> str:
    parts = [f"Repository: github.com/{snap.name} at commit {snap.sha[:12]}"]
    if snap.description:
        parts.append(f"Description: {snap.description}")
    parts.append(f"{len(snap.files)} source files were downloaded" + (", more were skipped as too big." if snap.truncated else "."))
    parts.append("Top of the tree:\n" + github.tree(snap, "", limit=120))
    if readme := github.readme(snap):
        parts.append("<readme>\n" + readme + "\n</readme>")
    return "\n\n".join(parts)


def _run_read_tool(snap: github.Snapshot, name: str, args: dict[str, Any], progress: Progress) -> str:
    if name == "list_files":
        progress(f"Looking in {args['path'] or 'the top folder'}")
        return github.tree(snap, args["path"])
    if name == "read_file":
        progress(f"Reading {args['path']}")
        return github.read(snap, args["path"], args.get("start_line") or 1, args.get("end_line") or 0)
    if name == "search":
        progress(f"Searching for {args['pattern']!r}")
        return github.search(snap, args["pattern"], args.get("path") or "")
    raise ValueError(f"There is no tool called {name}.")


def write_repo_lesson(snap: github.Snapshot, question: str, level: str, minutes: int, progress: Progress = lambda _: None) -> tuple[Storyboard, list[Call]]:
    words = minutes * 150
    scenes = max(4, min(MAX_SCENES, round(minutes * 2.3) + 1))
    messages: list[dict[str, Any]] = [{
        "role": "user",
        "content": (
            f"{_repo_brief(snap)}\n\nWhat they want to learn: {question}\n\n"
            f"Audience: {LEVELS.get(level, LEVELS['intro'])}.\n"
            f"Length: about {minutes} minutes spoken, so about {words} words of narration over about {scenes} scenes."
        ),
    }]
    calls: list[Call] = []
    submissions = 0
    nudged = False
    try:
        for _ in range(40):
            resp, call = _call(max_tokens=32000, output_config={"effort": "medium"}, system=REPO_SYSTEM,
                               tools=[*READ_TOOLS, SUBMIT_TOOL], messages=messages)
            calls.append(call)
            uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
            messages.append({"role": "assistant", "content": resp.content})
            if not uses:
                if nudged:
                    raise AIError("ai_no_lesson", "Claude read the code but didn't hand in a lesson. Try again, or ask a narrower question.", 502)
                nudged = True
                messages.append({"role": "user", "content": "Hand in the lesson now with submit_lesson."})
                continue
            results = []
            for use in uses:
                args = dict(use.input)
                if use.name == "submit_lesson":
                    submissions += 1
                    progress("Checking every citation against the code")
                    try:
                        board = Storyboard.model_validate(args)
                    except ValidationError as exc:
                        results.append({"type": "tool_result", "tool_use_id": use.id, "is_error": True, "content": f"The lesson doesn't fit the schema: {exc.errors()[0]['msg']} at {exc.errors()[0]['loc']}."})
                        continue
                    issues = grounding.problems(board, snap)
                    if not issues or submissions >= 3:
                        return grounding.ground(board, snap), calls
                    results.append({"type": "tool_result", "tool_use_id": use.id, "is_error": True, "content": "Fix these and submit again:\n- " + "\n- ".join(issues)})
                    continue
                try:
                    results.append({"type": "tool_result", "tool_use_id": use.id, "content": _run_read_tool(snap, use.name, args, progress)})
                except (ValueError, KeyError) as exc:
                    results.append({"type": "tool_result", "tool_use_id": use.id, "is_error": True, "content": f"Error: {exc}"})
            messages.append({"role": "user", "content": results})
        raise AIError("ai_loop", "Claude kept reading without finishing the lesson. Try a narrower question.", 502)
    except AIError as exc:
        exc.calls = calls + exc.calls
        raise
