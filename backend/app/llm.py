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

from app.storyboard import LAYOUTS, MAX_ITEMS, MAX_SCENES, Scene, Storyboard, next_scene_id, normalize, strict_json_schema

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AIError(Exception):
    """A failure the page can explain in one sentence."""

    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


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
    if resp.stop_reason == "refusal":
        raise AIError("ai_refused", "Claude declined to write this. Try rewording the topic.", 422)
    if resp.stop_reason == "max_tokens":
        raise AIError("ai_too_long", "The lesson came out too long to finish. Try a shorter length.", 502)
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
        raise AIError("ai_bad_output", "Claude's lesson didn't come out in a shape the editor can use. Try again.", 502) from exc
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


def edit_storyboard(board: Storyboard, instruction: str, scene_id: str | None, notes: str = "") -> EditOutcome:
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

    for _ in range(8):
        resp, call = _call(
            max_tokens=16000,
            output_config={"effort": "medium"},
            system=EDIT_SYSTEM,
            tools=EDIT_TOOLS,
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
                current, text = _apply(current, use.name, dict(use.input), changes)
                results.append({"type": "tool_result", "tool_use_id": use.id, "content": text})
            except (ValueError, KeyError, ValidationError) as exc:
                results.append({"type": "tool_result", "tool_use_id": use.id, "content": f"Error: {exc}", "is_error": True})
        messages.append({"role": "user", "content": results})

    raise AIError("ai_loop", "Claude kept going without finishing the edit. Try a simpler request.", 502)
