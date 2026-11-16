"""The storyboard: the one document Claude writes, the voice reads and the editor draws.

A lesson is a list of scenes. Each scene has a layout, a few things on screen and the
narration spoken over it. Items appear one at a time: `at` is the index of the narration
sentence during which the item shows up (0 = with the first sentence).

Every field is required so the same models can serve as Claude's structured output
schema (strict mode wants every property listed). "Nothing" is an empty string or an
empty list, never a missing key.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Layout = Literal["title", "points", "steps", "compare", "definition", "example", "code", "summary"]

LAYOUTS: dict[str, str] = {
    "title": "Opening card: heading and subheading only, no items.",
    "points": "Two to four key points, each a short line with an optional detail.",
    "steps": "A numbered sequence of two to five steps.",
    "compare": "Exactly two items side by side: text is each side's name, detail its description.",
    "definition": "One term in the heading, its definition as the single item, optional example as detail.",
    "example": "A worked example: the setup as subheading, then each line of working as an item.",
    "code": "A short code listing in `code` (at most 14 lines), items point out what matters.",
    "summary": "The takeaways, two to four items. Usually the last scene.",
}

MAX_SCENES = 12
MAX_ITEMS = 5


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Item(Strict):
    text: str = Field(description="What appears on screen. Short: at most 9 words.")
    detail: str = Field(description="A smaller second line, or an empty string.")
    at: int = Field(ge=0, description="Index of the narration sentence during which this item appears.")


class Scene(Strict):
    id: str = Field(description="Stable id: s1, s2, ... Never reuse an id within a lesson.")
    layout: Layout
    heading: str = Field(description="The scene's title on screen. At most 8 words.")
    subheading: str = Field(description="One short line under the heading, or an empty string.")
    items: list[Item] = Field(max_length=MAX_ITEMS)
    code: str = Field(description="Code for the code layout; an empty string otherwise.")
    narration: str = Field(
        description="What the voice says over this scene, written for the ear: 2 to 5 short sentences, "
        "plain words, numbers and symbols written the way they are said."
    )


class Storyboard(Strict):
    title: str = Field(description="The lesson's title. At most 8 words.")
    summary: str = Field(description="One sentence: what someone will understand after watching.")
    scenes: list[Scene] = Field(min_length=1, max_length=MAX_SCENES)


# ---------------------------------------------------------------- narration timing

_SENTENCE = re.compile(r"[^.!?]+(?:[.!?]+[\"')\]]*|$)")


def sentences(text: str) -> list[tuple[int, int]]:
    """Character spans of each sentence in `text`. Used to time reveals against the voice."""
    spans = []
    for m in _SENTENCE.finditer(text):
        start, end = m.start(), m.end()
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end > start:
            spans.append((start, end))
    return spans or [(0, len(text))]


def normalize(board: Storyboard) -> Storyboard:
    """Repair what a model can get slightly wrong without changing what it meant:
    unique scene ids, reveal indexes inside the narration, no items on a title card."""
    board = board.model_copy(deep=True)
    seen: set[str] = set()
    next_n = 1 + max((int(s.id[1:]) for s in board.scenes if re.fullmatch(r"s\d+", s.id)), default=0)
    for scene in board.scenes:
        if not re.fullmatch(r"s\d+", scene.id) or scene.id in seen:
            scene.id = f"s{next_n}"
            next_n += 1
        seen.add(scene.id)
        last = len(sentences(scene.narration)) - 1
        for item in scene.items:
            item.at = min(item.at, last)
        if scene.layout == "title":
            scene.items = []
        if scene.layout != "code":
            scene.code = ""
    return board


def next_scene_id(board: Storyboard) -> str:
    nums = [int(s.id[1:]) for s in board.scenes if re.fullmatch(r"s\d+", s.id)]
    return f"s{max(nums, default=0) + 1}"


# ---------------------------------------------------------------- schema export


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON Schema with refs inlined and every object closed, the shape
    Claude's structured outputs and strict tools accept."""
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(deepcopy(defs[node["$ref"].split("/")[-1]]))
            out = {}
            for k, v in node.items():
                if k == "properties":  # property names are data, not keywords: keep them all
                    out[k] = {name: walk(sub) for name, sub in v.items()}
                elif k in ("title", "default") and not isinstance(v, (dict, list)):
                    continue  # schema annotations the API doesn't need
                else:
                    out[k] = walk(v)
            if out.get("type") == "object":
                out["additionalProperties"] = False
                out["required"] = list(out.get("properties", {}).keys())
            # constraints structured outputs do not enforce; Pydantic checks them after
            for key in ("minimum", "maxItems", "minItems", "maxLength", "minLength"):
                out.pop(key, None)
            return out
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(raw)
