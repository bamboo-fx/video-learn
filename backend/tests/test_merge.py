"""Two people's changes to one storyboard, merged scene by scene (app/merge.py)."""

import copy

from app.merge import merge
from app.storyboard import MAX_SCENES, Storyboard


def board(d):
    return Storyboard.model_validate(d)


def edit(example, fn):
    d = copy.deepcopy(example)
    fn(d)
    return d


def scene(d, sid):
    return next(s for s in d["scenes"] if s["id"] == sid)


def merged(example, theirs, mine):
    out, clashes = merge(board(example), board(theirs), board(mine))
    return out.model_dump(), clashes


def test_changes_to_different_scenes_are_both_kept(example):
    theirs = edit(example, lambda d: scene(d, "s2").update(heading="Their heading"))
    mine = edit(example, lambda d: scene(d, "s4").update(narration="My narration."))
    out, clashes = merged(example, theirs, mine)
    assert scene(out, "s2")["heading"] == "Their heading"
    assert scene(out, "s4")["narration"] == "My narration."
    assert clashes == []


def test_different_fields_of_one_scene_are_both_kept(example):
    theirs = edit(example, lambda d: scene(d, "s3").update(heading="Their heading"))
    mine = edit(example, lambda d: scene(d, "s3").update(narration="My narration."))
    out, clashes = merged(example, theirs, mine)
    assert scene(out, "s3")["heading"] == "Their heading" and scene(out, "s3")["narration"] == "My narration."
    assert clashes == []


def test_the_same_field_changed_twice_keeps_mine_and_says_so(example):
    theirs = edit(example, lambda d: scene(d, "s3").update(narration="Their narration."))
    mine = edit(example, lambda d: scene(d, "s3").update(narration="My narration."))
    out, clashes = merged(example, theirs, mine)
    assert scene(out, "s3")["narration"] == "My narration."
    assert len(clashes) == 1 and clashes[0]["scene_id"] == "s3" and "narration" in clashes[0]["note"]


def test_the_same_change_made_twice_is_not_a_clash(example):
    same = edit(example, lambda d: scene(d, "s3").update(narration="We agree."))
    out, clashes = merged(example, same, copy.deepcopy(same))
    assert scene(out, "s3")["narration"] == "We agree." and clashes == []


def test_scenes_added_by_each_person_land_where_they_put_them(example):
    def add(d, after, sid, heading):
        new = {**copy.deepcopy(d["scenes"][1]), "id": sid, "heading": heading}
        d["scenes"].insert(next(i for i, s in enumerate(d["scenes"]) if s["id"] == after) + 1, new)

    theirs = edit(example, lambda d: add(d, "s2", "s50", "Theirs"))
    mine = edit(example, lambda d: add(d, "s5", "s60", "Mine"))
    out, clashes = merged(example, theirs, mine)
    ids = [s["id"] for s in out["scenes"]]
    assert ids.index("s50") == ids.index("s2") + 1 and ids.index("s60") == ids.index("s5") + 1
    assert len(ids) == len(example["scenes"]) + 2 and clashes == []


def test_two_new_scenes_with_the_same_id_are_both_kept(example):
    def add(d, heading):
        d["scenes"].append({**copy.deepcopy(d["scenes"][1]), "id": "s8", "heading": heading})

    out, _ = merged(example, edit(example, lambda d: add(d, "Theirs")), edit(example, lambda d: add(d, "Mine")))
    headings = [s["heading"] for s in out["scenes"]]
    assert "Theirs" in headings and "Mine" in headings
    assert len({s["id"] for s in out["scenes"]}) == len(out["scenes"])


def test_a_deleted_scene_stays_deleted_unless_the_other_person_changed_it(example):
    gone = edit(example, lambda d: d["scenes"].pop(2))  # s3
    untouched = copy.deepcopy(example)
    out, clashes = merged(example, gone, untouched)
    assert "s3" not in [s["id"] for s in out["scenes"]] and clashes == []
    out, clashes = merged(example, untouched, gone)
    assert "s3" not in [s["id"] for s in out["scenes"]] and clashes == []

    changed = edit(example, lambda d: scene(d, "s3").update(narration="Still working on this."))
    out, clashes = merged(example, gone, changed)  # they deleted what I was changing
    assert scene(out, "s3")["narration"] == "Still working on this." and len(clashes) == 1
    out, clashes = merged(example, changed, gone)  # I deleted what they were changing
    assert scene(out, "s3")["narration"] == "Still working on this." and len(clashes) == 1


def test_a_reorder_by_one_person_carries_the_other_persons_edits(example):
    theirs = edit(example, lambda d: d["scenes"].insert(1, d["scenes"].pop(4)))  # s5 up to second
    mine = edit(example, lambda d: scene(d, "s5").update(heading="Renamed by me"))
    out, clashes = merged(example, theirs, mine)
    assert [s["id"] for s in out["scenes"]] == [s["id"] for s in theirs["scenes"]]
    assert scene(out, "s5")["heading"] == "Renamed by me" and clashes == []


def test_title_and_summary_merge_like_fields(example):
    theirs = edit(example, lambda d: d.update(title="Their title"))
    mine = edit(example, lambda d: d.update(summary="My summary."))
    out, clashes = merged(example, theirs, mine)
    assert out["title"] == "Their title" and out["summary"] == "My summary." and clashes == []


def test_a_merge_never_makes_a_lesson_too_long(example):
    def fill(d, start):
        for n in range(start, start + MAX_SCENES - len(d["scenes"])):
            d["scenes"].append({**copy.deepcopy(d["scenes"][1]), "id": f"s{n}", "heading": f"New {n}"})

    out, clashes = merged(example, edit(example, lambda d: fill(d, 100)), edit(example, lambda d: fill(d, 200)))
    assert len(out["scenes"]) == MAX_SCENES
    assert all(s["id"] in {x["id"] for x in out["scenes"]} for s in example["scenes"])  # nobody's old scenes were dropped
    assert clashes and "wasn't kept" in clashes[0]["note"]
