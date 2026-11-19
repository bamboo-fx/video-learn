"""Merging two people's changes to one lesson, the way git merges two branches.

When two people edit the same lesson, each save says which storyboard it started from (the
base). If someone else saved in between, the server doesn't let the later save erase the
earlier one: it compares both against the base and keeps both sets of changes.

- Scenes are matched by id. A scene only one person touched takes that person's version.
- A scene both touched is merged field by field (heading, narration, items, ...), so one
  person can fix the narration while the other changes the layout.
- Where both changed the same field, the save being made now wins ("mine"), and the clash
  is reported so the page can say so. The other version is still in the history.
- Nothing either person wrote is dropped silently: a scene one deleted while the other was
  changing it is kept.

Pure functions over storyboards; no database, no clock.
"""

from __future__ import annotations

import re
from typing import Any

from app.storyboard import MAX_SCENES, Storyboard

# what a scene is made of, with the word the page uses for it when two changes clash
SCENE_FIELDS: dict[str, str] = {
    "layout": "layout",
    "heading": "heading",
    "subheading": "subheading",
    "items": "on-screen points",
    "code": "code",
    "source": "source",
    "narration": "narration",
}
LESSON_FIELDS: dict[str, str] = {"title": "title", "summary": "summary"}


def _clash(scene: dict[str, Any] | None, note: str) -> dict[str, str]:
    return {"scene_id": scene["id"] if scene else "", "heading": scene["heading"] if scene else "", "note": note}


def _name(scene: dict[str, Any]) -> str:
    return f"“{scene['heading']}”" if scene.get("heading") else "A scene"


def _free_id(taken: set[str]) -> str:
    nums = [int(i[1:]) for i in taken if re.fullmatch(r"s\d+", i)]
    return f"s{max(nums, default=0) + 1}"


def _order(base: list[str], theirs: list[str], mine: list[str], alive: set[str], clashes: list[dict[str, str]]) -> list[str]:
    """The merged scene order. Whoever moved scenes sets the order; scenes the other person
    added go in after the scene they followed."""
    common = set(base) & set(theirs) & set(mine)

    def moved(ids: list[str]) -> bool:
        return [i for i in ids if i in common] != [i for i in base if i in common]

    i_moved, they_moved = moved(mine), moved(theirs)
    if i_moved and they_moved and [i for i in mine if i in common] != [i for i in theirs if i in common]:
        clashes.append(_clash(None, "You both reordered the scenes. Your order was kept."))
    first, second = (mine, theirs) if i_moved else (theirs, mine)
    out = [i for i in first if i in alive]
    placed = set(out)
    for k, sid in enumerate(second):
        if sid not in alive or sid in placed:
            continue
        at = 0
        for earlier in reversed(second[:k]):
            if earlier in placed:
                at = out.index(earlier) + 1
                break
        out.insert(at, sid)
        placed.add(sid)
    return out


def merge(base: Storyboard, theirs: Storyboard, mine: Storyboard) -> tuple[Storyboard, list[dict[str, str]]]:
    """Three-way merge. `base` is what `mine` was edited from; `theirs` is what the lesson is
    now. Returns the merged storyboard and the places where both changed the same thing."""
    b, t, m = base.model_dump(), theirs.model_dump(), mine.model_dump()
    clashes: list[dict[str, str]] = []
    out: dict[str, Any] = {}

    for field, word in LESSON_FIELDS.items():
        if m[field] != b[field]:
            if t[field] not in (b[field], m[field]):
                clashes.append(_clash(None, f"You both changed the lesson's {word}. Yours was kept."))
            out[field] = m[field]
        else:
            out[field] = t[field]

    bs = {s["id"]: s for s in b["scenes"]}
    ts = {s["id"]: s for s in t["scenes"]}
    ms = {s["id"]: s for s in m["scenes"]}
    scenes: dict[str, dict[str, Any]] = {}
    mine_only: list[str] = []  # scenes only this save added, newest ids last
    renamed: dict[str, str] = {}

    for sid in dict.fromkeys([*bs, *ts, *ms]):
        old, theirs_s, mine_s = bs.get(sid), ts.get(sid), ms.get(sid)
        if old is None:
            if theirs_s is not None:
                scenes[sid] = theirs_s
            if mine_s is not None and mine_s != theirs_s:
                if theirs_s is None:
                    scenes[sid] = mine_s
                    mine_only.append(sid)
                else:
                    renamed[sid] = ""  # both added a scene under the same id: mine gets a new one below
            continue
        if theirs_s is None and mine_s is None:
            continue
        if theirs_s is None:
            if mine_s != old:
                scenes[sid] = mine_s
                clashes.append(_clash(mine_s, f"{_name(mine_s)} was deleted by someone else while you were changing it. It was kept."))
            continue
        if mine_s is None:
            if theirs_s != old:
                scenes[sid] = theirs_s
                clashes.append(_clash(theirs_s, f"You deleted {_name(theirs_s)}, but someone else had just changed it. It was kept."))
            continue
        merged = {"id": sid}
        for field, word in SCENE_FIELDS.items():
            if mine_s[field] != old[field]:
                if theirs_s[field] not in (old[field], mine_s[field]):
                    clashes.append(_clash(mine_s, f"{_name(mine_s)}: you both changed the {word}. Yours was kept."))
                merged[field] = mine_s[field]
            else:
                merged[field] = theirs_s[field]
        scenes[sid] = merged

    for sid in renamed:
        new_id = _free_id(set(scenes) | set(bs) | set(ts) | set(ms) | set(renamed.values()))
        renamed[sid] = new_id
        scenes[new_id] = {**ms[sid], "id": new_id}
        mine_only.append(new_id)

    # the order, with my scenes that had to be renamed standing where I put them
    my_order = [s["id"] for s in m["scenes"]]
    their_order = [s["id"] for s in t["scenes"]]
    if renamed:
        # the shared id now means their scene; mine follows it under its new id
        my_order = [x for sid in my_order for x in ((sid, renamed[sid]) if sid in renamed else (sid,))]
    order = _order(list(bs), their_order, my_order, set(scenes), clashes)

    while len(order) > MAX_SCENES:
        drop = next((i for i in reversed(order) if i in mine_only), order[-1])
        clashes.append(_clash(scenes[drop], f"A lesson holds {MAX_SCENES} scenes, so {_name(scenes[drop])} wasn't kept."))
        order.remove(drop)
    if not order:  # each deleted what the other kept; a lesson needs a scene
        return mine, clashes

    out["scenes"] = [scenes[i] for i in order]
    return Storyboard.model_validate(out), clashes
