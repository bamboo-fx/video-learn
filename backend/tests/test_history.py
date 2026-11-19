"""Version history, and editing a lesson with other people."""

import copy
from datetime import timedelta

from sqlmodel import Session, select

from app import history
from app.db import engine
from app.models import Version, now


def who(name):
    return {"X-Owner": f"history-{name}-0123456789abcdef"}


def make(client, owner, board=None, topic="A lesson with a past"):
    p = client.post("/api/projects", json={"topic": topic}, headers=owner).json()
    if board is not None:
        r = client.put(f"/api/projects/{p['id']}/storyboard", json={"storyboard": board}, headers=owner)
        assert r.status_code == 200, r.text
        p = r.json()
    return p


def save(client, pid, board, headers, base=None):
    body = {"storyboard": board} if base is None else {"storyboard": board, "base": base}
    return client.put(f"/api/projects/{pid}/storyboard", json=body, headers=headers)


def versions(client, pid, headers):
    r = client.get(f"/api/projects/{pid}/versions", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["versions"]


def changed(board, sid, **fields):
    out = copy.deepcopy(board)
    next(s for s in out["scenes"] if s["id"] == sid).update(fields)
    return out


def age_versions(pid, minutes):
    """Pretend the lesson's versions were made a while ago, so the next save starts a new one."""
    with Session(engine) as s:
        for v in s.exec(select(Version).where(Version.project_id == pid)).all():
            v.created_at = v.updated_at = now() - timedelta(minutes=minutes)
            s.add(v)
        s.commit()


def invite(client, pid, owner, guest, name="Sam"):
    token = client.post(f"/api/projects/{pid}/invite", headers=owner).json()["invite_token"]
    r = client.post(f"/api/projects/{pid}/join", json={"token": token, "name": name}, headers=guest)
    assert r.status_code == 200, r.text
    return token


# ---------------------------------------------------------------- history


def test_saves_close_together_fold_into_one_version(client, example):
    owner = who("fold")
    p = make(client, owner, example)
    assert [v["number"] for v in versions(client, p["id"], owner)] == [1]
    for text in ("One.", "One. Two.", "One. Two. Three."):
        save(client, p["id"], changed(example, "s2", narration=text), owner)
    vs = versions(client, p["id"], owner)
    assert len(vs) == 1 and vs[0]["current"] is True

    age_versions(p["id"], 30)
    # (narration as long as the last, so the reveal cues on the scene's items don't move)
    save(client, p["id"], changed(example, "s2", narration="One. Two. Three, but later."), owner)
    vs = versions(client, p["id"], owner)
    assert [v["number"] for v in vs] == [2, 1] and vs[0]["current"] and not vs[1]["current"]
    assert vs[0]["changes"] == [{"kind": "changed", "scene_id": "s2", "heading": example["scenes"][1]["heading"], "fields": ["narration"]}]


def test_a_save_that_changes_nothing_is_not_a_version(client, example):
    owner = who("nothing")
    p = make(client, owner, example)
    age_versions(p["id"], 30)
    save(client, p["id"], example, owner)
    assert len(versions(client, p["id"], owner)) == 1


def test_going_back_adds_a_version_and_can_be_undone(client, example):
    owner = who("restore")
    p = make(client, owner, example)
    age_versions(p["id"], 30)
    edited = changed(example, "s3", heading="A worse heading")
    edited["scenes"].pop()
    save(client, p["id"], edited, owner)
    first = versions(client, p["id"], owner)[-1]

    seen = client.get(f"/api/projects/{p['id']}/versions/{first['id']}", headers=owner).json()
    assert seen["storyboard"]["scenes"][2]["heading"] == example["scenes"][2]["heading"]

    r = client.post(f"/api/projects/{p['id']}/versions/{first['id']}/restore", headers=owner)
    assert r.status_code == 200, r.text
    assert len(r.json()["storyboard"]["scenes"]) == len(example["scenes"]) and r.json()["rev"] == 3
    vs = versions(client, p["id"], owner)
    assert [v["kind"] for v in vs] == ["restore", "hand", "hand"] and "version 1" in vs[0]["message"]
    assert {c["kind"] for c in vs[0]["changes"]} == {"changed", "added"}

    # the version that was left behind is still there to go back to
    r = client.post(f"/api/projects/{p['id']}/versions/{vs[1]['id']}/restore", headers=owner)
    assert r.json()["storyboard"]["scenes"][2]["heading"] == "A worse heading"
    assert len(versions(client, p["id"], owner)) == 4


def test_a_named_version_is_kept_apart(client, example):
    owner = who("named")
    p = make(client, owner, example)
    r = client.post(f"/api/projects/{p['id']}/versions", json={"name": "  Before the review "}, headers=owner)
    assert r.status_code == 201 and r.json()["name"] == "Before the review" and r.json()["number"] == 1
    # the next hand save doesn't fold into a version someone named
    save(client, p["id"], changed(example, "s2", heading="After"), owner)
    vs = versions(client, p["id"], owner)
    assert [(v["number"], v["name"]) for v in vs] == [(2, ""), (1, "Before the review")]
    assert client.post(f"/api/projects/{p['id']}/versions", json={"name": " "}, headers=owner).status_code == 422


def test_writing_and_ai_edits_are_versions(client, example, monkeypatch):
    from app import llm
    from app.storyboard import Storyboard

    owner = who("ai")
    monkeypatch.setattr(llm, "write_storyboard", lambda *a: (Storyboard.model_validate(example), llm.Call("claude-test", 1, 1, 1)))
    p = client.post("/api/projects", json={"topic": "History of a written lesson"}, headers=owner).json()
    assert client.post(f"/api/projects/{p['id']}/write", headers=owner).status_code == 200

    def fake_edit(board, instruction, scene_id, notes="", snap=None, progress=None):
        out = board.model_copy(deep=True)
        out.scenes[1].heading = "Simpler"
        return llm.EditOutcome(out, "Made it simpler.", [{"kind": "updated", "scene_id": "s2", "note": "Simpler"}], [llm.Call("claude-test", 1, 1, 1)])

    monkeypatch.setattr(llm, "edit_storyboard", fake_edit)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    r = client.post(f"/api/projects/{p['id']}/edit", json={"instruction": "Make scene 2 simpler"}, headers=owner)
    assert r.status_code == 200, r.text
    vs = versions(client, p["id"], owner)
    assert [(v["kind"], v["message"]) for v in vs] == [("ai", "Make scene 2 simpler"), ("write", "Claude wrote the lesson")]
    assert r.json()["project"]["rev"] == 2

    # a rewrite keeps the lesson it replaced
    assert client.post(f"/api/projects/{p['id']}/write", headers=owner).status_code == 200
    vs = versions(client, p["id"], owner)
    assert vs[0]["message"] == "Claude rewrote the lesson" and len(vs) == 3


def test_a_lesson_from_before_history_gets_its_old_storyboard_as_the_first_version(client, example):
    owner = who("legacy")
    p = make(client, owner, example)
    with Session(engine) as s:
        for v in s.exec(select(Version).where(Version.project_id == p["id"])).all():
            s.delete(v)
        s.commit()
    assert versions(client, p["id"], owner) == []
    save(client, p["id"], changed(example, "s2", heading="First change since"), owner)
    vs = versions(client, p["id"], owner)
    assert [v["kind"] for v in vs] == ["hand", "start"]
    old = client.get(f"/api/projects/{p['id']}/versions/{vs[1]['id']}", headers=owner).json()
    assert old["storyboard"]["scenes"][1]["heading"] == example["scenes"][1]["heading"]


def test_history_is_for_editors_and_goes_with_the_lesson(client, example):
    owner, stranger = who("private"), who("stranger")
    p = make(client, owner, example)
    assert client.get(f"/api/projects/{p['id']}/versions", headers=stranger).status_code == 403
    v = versions(client, p["id"], owner)[0]
    assert client.get(f"/api/projects/{p['id']}/versions/{v['id']}", headers=stranger).status_code == 403
    assert client.post(f"/api/projects/{p['id']}/versions/{v['id']}/restore", headers=stranger).status_code == 403
    other = make(client, owner, example, topic="Another lesson entirely")
    assert client.get(f"/api/projects/{other['id']}/versions/{v['id']}", headers=owner).status_code == 404

    assert client.delete(f"/api/projects/{p['id']}", headers=owner).status_code == 204
    with Session(engine) as s:
        assert s.exec(select(Version).where(Version.project_id == p["id"])).first() is None


def test_old_unnamed_versions_are_pruned(example, monkeypatch):
    monkeypatch.setattr(history, "KEEP", 3)
    with Session(engine) as s:
        for n in range(6):
            b = changed(example, "s2", heading=f"Heading {n}")
            v = history.record(s, "prune-test", b, kind="ai", message=str(n))
            if n == 0:
                v.name = "Keep me"
        s.commit()
        left = s.exec(select(Version).where(Version.project_id == "prune-test").order_by(Version.id)).all()
        assert [v.message for v in left] == ["0", "3", "4", "5"]


# ---------------------------------------------------------------- editing together


def test_an_invited_person_can_edit_and_a_stranger_cannot(client, example):
    owner, guest, stranger = who("host"), who("guest"), who("nobody")
    p = make(client, owner, example)
    assert p["people"] == [{"id": 0, "name": "", "role": "owner", "you": True}] and p["invite_token"] == ""
    assert save(client, p["id"], example, guest).status_code == 403

    token = client.post(f"/api/projects/{p['id']}/invite", headers=owner).json()["invite_token"]
    assert len(token) >= 20
    assert client.post(f"/api/projects/{p['id']}/invite", headers=owner).json()["invite_token"] == token  # the same link again
    assert client.post(f"/api/projects/{p['id']}/invite", headers=guest).status_code == 403
    r = client.post(f"/api/projects/{p['id']}/join", json={"token": "not-the-right-token"}, headers=stranger)
    assert r.status_code == 403 and r.json()["error"]["code"] == "bad_invite"

    joined = client.post(f"/api/projects/{p['id']}/join", json={"token": token, "name": "Sam"}, headers=guest).json()
    assert joined["can_edit"] is True and joined["is_owner"] is False and joined["my_name"] == "Sam"
    assert joined["invite_token"] == ""  # only the owner sees the link
    assert [(x["name"], x["role"], x["you"]) for x in joined["people"]] == [("", "owner", False), ("Sam", "editor", True)]
    assert "0123456789" not in str(joined["people"])  # browser ids stay on the server

    r = save(client, p["id"], changed(example, "s2", heading="From Sam"), guest)
    assert r.status_code == 200 and r.json()["storyboard"]["scenes"][1]["heading"] == "From Sam"
    # hand saves close together are one version, by everyone who made them; before anyone
    # else could edit, there were no names to tell apart
    assert versions(client, p["id"], owner)[0]["authors"] == ["Sam"]
    save(client, p["id"], changed(example, "s2", heading="From the owner"), owner)
    assert versions(client, p["id"], owner)[0]["authors"] == ["Sam", "The owner"]

    # a share link still only watches
    seen = client.get(f"/api/projects/{p['id']}", headers=stranger).json()
    assert seen["can_edit"] is False and seen["people"] == []
    assert save(client, p["id"], example, stranger).status_code == 403

    # an editor can't do the owner's things
    assert client.delete(f"/api/projects/{p['id']}", headers=guest).status_code == 403
    assert client.post(f"/api/projects/{p['id']}/write", headers=guest).status_code == 403
    assert client.delete(f"/api/projects/{p['id']}/invite", headers=guest).status_code == 403

    # it shows up in the guest's list, marked as shared
    mine = {x["id"]: x for x in client.get("/api/projects", headers=guest).json()["projects"]}
    assert mine[p["id"]]["shared"] is True
    assert {x["id"]: x for x in client.get("/api/projects", headers=owner).json()["projects"]}[p["id"]]["shared"] is False


def test_turning_the_link_off_and_removing_people(client, example):
    owner, guest, late = who("gate"), who("in"), who("late")
    p = make(client, owner, example)
    token = invite(client, p["id"], owner, guest)
    assert client.delete(f"/api/projects/{p['id']}/invite", headers=owner).json()["invite_token"] == ""
    assert client.post(f"/api/projects/{p['id']}/join", json={"token": token}, headers=late).status_code == 403
    assert save(client, p["id"], example, guest).status_code == 200  # already in

    new = client.post(f"/api/projects/{p['id']}/invite", json={"reset": True}, headers=owner).json()["invite_token"]
    assert new and new != token
    member = client.get(f"/api/projects/{p['id']}", headers=owner).json()["people"][1]
    assert client.delete(f"/api/projects/{p['id']}/members/{member['id']}", headers=late).status_code == 403
    after = client.delete(f"/api/projects/{p['id']}/members/{member['id']}", headers=owner).json()
    assert len(after["people"]) == 1
    assert save(client, p["id"], example, guest).status_code == 403

    # someone who joined can leave on their own
    client.post(f"/api/projects/{p['id']}/join", json={"token": new}, headers=guest)
    me = next(x for x in client.get(f"/api/projects/{p['id']}", headers=guest).json()["people"] if x["you"])
    left = client.delete(f"/api/projects/{p['id']}/members/{me['id']}", headers=guest).json()
    assert left["can_edit"] is False


def test_names_show_on_changes(client, example):
    owner, guest = who("named-owner"), who("named-guest")
    p = make(client, owner, example)
    invite(client, p["id"], owner, guest, name="")
    assert client.put(f"/api/projects/{p['id']}/me", json={"name": " Kai "}, headers=owner).json()["my_name"] == "Kai"
    out = client.put(f"/api/projects/{p['id']}/me", json={"name": "Ren"}, headers=guest).json()
    assert [x["name"] for x in out["people"]] == ["Kai", "Ren"]
    assert client.put(f"/api/projects/{p['id']}/me", json={"name": "x"}, headers=who("outsider")).status_code == 403
    age_versions(p["id"], 30)
    save(client, p["id"], changed(example, "s2", heading="By Ren"), guest)
    assert versions(client, p["id"], guest)[0]["authors"] == ["Ren"]


def test_two_people_saving_from_the_same_start_keep_both_changes(client, example):
    owner, guest = who("merge-a"), who("merge-b")
    p = make(client, owner, example)
    invite(client, p["id"], owner, guest)
    start = client.get(f"/api/projects/{p['id']}", headers=owner).json()["storyboard"]

    a = save(client, p["id"], changed(start, "s2", heading="Owner's heading"), owner, base=start)
    assert a.status_code == 200 and a.json()["conflicts"] == []
    # the guest never saw that save: without a merge, theirs would undo it
    b = save(client, p["id"], changed(start, "s5", narration="Guest's narration."), guest, base=start)
    assert b.status_code == 200 and b.json()["conflicts"] == []
    scenes = {s["id"]: s for s in b.json()["storyboard"]["scenes"]}
    assert scenes["s2"]["heading"] == "Owner's heading" and scenes["s5"]["narration"] == "Guest's narration."
    assert b.json()["rev"] == a.json()["rev"] + 1

    # the same field: the later save wins, says so, and the other is in the history
    now_ = b.json()["storyboard"]
    save(client, p["id"], changed(now_, "s3", heading="Owner again"), owner, base=now_)
    c = save(client, p["id"], changed(now_, "s3", heading="Guest again"), guest, base=now_)
    assert c.json()["storyboard"]["scenes"][2]["heading"] == "Guest again"
    assert len(c.json()["conflicts"]) == 1 and c.json()["conflicts"][0]["scene_id"] == "s3"

    # without a base (an old page), a save still replaces the lesson as it always did
    d = save(client, p["id"], start, owner)
    assert d.json()["storyboard"] == start and d.json()["conflicts"] == []


def test_the_rev_endpoint_reports_changes_and_editors(client, example):
    owner, guest = who("rev-a"), who("rev-b")
    p = make(client, owner, example)
    assert client.get(f"/api/projects/{p['id']}/rev").json() == {"rev": 1, "status": "ready", "editors": 0}
    invite(client, p["id"], owner, guest)
    save(client, p["id"], changed(example, "s2", heading="Again"), guest)
    assert client.get(f"/api/projects/{p['id']}/rev").json() == {"rev": 2, "status": "ready", "editors": 1}
    assert client.get("/api/projects/nope/rev").status_code == 404


def test_an_imported_lesson_starts_its_history(client, example):
    r = client.post("/api/import", json={"storyboard": example, "question": "How does history start?"})
    assert r.status_code == 201, r.text
    owner = who("importer")
    token = r.json()["url"].split("claim=")[1]
    assert client.post(f"/api/projects/{r.json()['id']}/claim", json={"token": token}, headers=owner).status_code == 200
    vs = versions(client, r.json()["id"], owner)
    assert [(v["kind"], v["message"]) for v in vs] == [("import", "Made with Claude Code")]
