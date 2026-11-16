"""Claude and ElevenLabs, with both faked: these tests never spend money."""

import json
from types import SimpleNamespace

import pytest

from app import llm, tts
from app.storyboard import Storyboard


def make_written(client, owner, example, monkeypatch, topic="Gradient descent"):
    monkeypatch.setattr(llm, "write_storyboard", lambda *a: (Storyboard.model_validate(example), llm.Call("claude-test", 1200, 3400, 900)))
    p = client.post("/api/projects", json={"topic": topic}, headers=owner).json()
    r = client.post(f"/api/projects/{p['id']}/write", headers=owner)
    assert r.status_code == 200, r.text
    return r.json()


def fake_speak(text, voice, model, prev="", nxt=""):
    words = []
    t = 0.0
    import re

    for m in re.finditer(r"\S+", text):
        words.append({"text": m.group(), "start_char": m.start(), "end_char": m.end(), "start": t, "end": t + 0.3})
        t += 0.35
    return tts.Spoken(audio=b"ID3fake-mp3-bytes" * 10, words=words, duration=t, ms=50)


# ---------------------------------------------------------------- writing


def test_write_saves_the_storyboard_and_logs_usage(client, owner, example, monkeypatch):
    p = make_written(client, owner, example, monkeypatch)
    assert p["status"] == "ready"
    assert p["title"] == example["title"]
    assert len(p["storyboard"]["scenes"]) == 7
    usage = client.get(f"/api/projects/{p['id']}/usage", headers=owner).json()["calls"]
    assert usage[0]["kind"] == "write" and usage[0]["output_tokens"] == 3400


def test_write_without_a_key_fails_honestly(client, owner):
    p = client.post("/api/projects", json={"topic": "Entropy"}, headers=owner).json()
    r = client.post(f"/api/projects/{p['id']}/write", headers=owner)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "ai_not_configured"
    assert "isn't set up" in r.json()["error"]["message"]
    after = client.get(f"/api/projects/{p['id']}", headers=owner).json()
    assert after["status"] == "failed" and "isn't set up" in after["error"]


def test_only_the_owner_can_start_a_write(client, owner, other):
    p = client.post("/api/projects", json={"topic": "Entropy"}, headers=owner).json()
    assert client.post(f"/api/projects/{p['id']}/write", headers=other).status_code == 403


def test_config_reports_missing_keys(client):
    assert client.get("/api/config").json() == {"ai": False, "voice": False}


# ---------------------------------------------------------------- voicing


def test_voice_a_scene_then_reuse_it(client, owner, example, monkeypatch):
    p = make_written(client, owner, example, monkeypatch)
    calls = []

    def counting(*a, **k):
        calls.append(a[0])
        return fake_speak(*a, **k)

    monkeypatch.setattr(tts, "speak", counting)
    v = client.post(f"/api/projects/{p['id']}/scenes/s2/voice", headers=owner).json()
    assert v["text"] == example["scenes"][1]["narration"]
    assert v["words"][0]["start_char"] == 0 and v["duration"] > 0

    # the same narration again costs nothing
    client.post(f"/api/projects/{p['id']}/scenes/s2/voice", headers=owner)
    assert len(calls) == 1

    got = client.get(f"/api/projects/{p['id']}", headers=owner).json()
    assert set(got["voices"]) == {"s2"}

    audio = client.get(v["url"])
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/mpeg"
    part = client.get(v["url"], headers={"Range": "bytes=0-9"})
    assert part.status_code == 206 and len(part.content) == 10


def test_editing_narration_makes_the_voice_stale(client, owner, example, monkeypatch):
    p = make_written(client, owner, example, monkeypatch)
    monkeypatch.setattr(tts, "speak", fake_speak)
    client.post(f"/api/projects/{p['id']}/scenes/s1/voice", headers=owner)
    example["scenes"][0]["narration"] = "A different first line."
    saved = client.put(f"/api/projects/{p['id']}/storyboard", json={"storyboard": example}, headers=owner).json()
    assert "s1" not in saved["voices"]


def test_voice_failure_is_explained(client, owner, example, monkeypatch):
    example["scenes"][0]["narration"] = "A line no other test has voiced."  # clips are shared, so avoid a cached one
    p = make_written(client, owner, example, monkeypatch)

    def broke(*a, **k):
        raise tts.VoiceError("voice_quota", "The voice service is out of credits for now.", 503)

    monkeypatch.setattr(tts, "speak", broke)
    r = client.post(f"/api/projects/{p['id']}/scenes/s1/voice", headers=owner)
    assert r.status_code == 503 and r.json()["error"]["code"] == "voice_quota"


def test_voice_without_a_key(monkeypatch):
    with pytest.raises(tts.VoiceError) as e:
        tts.speak("Hello there.", "v", "m")
    assert e.value.code == "voice_not_configured"


def test_daily_voice_limit(client, owner, example, monkeypatch):
    monkeypatch.setenv("LIMIT_VOICE_CHARS_PER_BROWSER", "50")
    p = make_written(client, owner, example, monkeypatch, topic="Limits")
    monkeypatch.setattr(tts, "speak", fake_speak)
    r = client.post(f"/api/projects/{p['id']}/scenes/s3/voice", headers=owner)
    assert r.status_code == 429 and "allowance" in r.json()["error"]["message"]


def test_words_from_alignment_keeps_character_offsets():
    text = "Hi there. Bye!"
    chars = list(text)
    al = {
        "characters": chars,
        "character_start_times_seconds": [i * 0.1 for i in range(len(chars))],
        "character_end_times_seconds": [i * 0.1 + 0.1 for i in range(len(chars))],
    }
    words = tts.words_from_alignment(text, al)
    assert [w["text"] for w in words] == ["Hi", "there.", "Bye!"]
    assert words[1]["start_char"] == 3 and words[1]["start"] == 0.3 and words[1]["end"] == 0.9


def test_voice_errors_map_to_sentences():
    import httpx

    quota = httpx.Response(401, json={"detail": {"status": "quota_exceeded", "message": "x"}})
    assert tts._voice_error(quota).code == "voice_quota"
    assert tts._voice_error(httpx.Response(401, json={"detail": "bad key"})).code == "voice_key_invalid"
    assert tts._voice_error(httpx.Response(500, text="boom")).code == "voice_down"


# ---------------------------------------------------------------- editing with tools


def scene_body(example, i, **patch):
    s = {k: v for k, v in example["scenes"][i].items() if k != "id"}
    s.update(patch)
    return s


def test_tool_apply_updates_inserts_moves_deletes(example):
    board = Storyboard.model_validate(example)
    changes = []
    board, _ = llm._apply(board, "update_scene", {"scene_id": "s2", "scene": scene_body(example, 1, heading="Loss, simply"), "note": "simpler"}, changes)
    assert board.scenes[1].heading == "Loss, simply" and board.scenes[1].id == "s2"
    board, msg = llm._apply(board, "insert_scene", {"after_scene_id": "s2", "scene": scene_body(example, 2, heading="An analogy"), "note": "added"}, changes)
    assert board.scenes[2].heading == "An analogy" and board.scenes[2].id == "s8"
    board, _ = llm._apply(board, "move_scene", {"scene_id": "s8", "after_scene_id": "", "note": "first"}, changes)
    assert board.scenes[0].id == "s8"
    board, _ = llm._apply(board, "delete_scene", {"scene_id": "s8", "note": "gone"}, changes)
    assert [s.id for s in board.scenes][:2] == ["s1", "s2"]
    assert [c["kind"] for c in changes] == ["updated", "inserted", "moved", "deleted"]
    with pytest.raises(ValueError):
        llm._apply(board, "update_scene", {"scene_id": "s99", "scene": scene_body(example, 0), "note": ""}, changes)


def test_edit_loop_runs_tools_until_claude_is_done(example, monkeypatch):
    board = Storyboard.model_validate(example)
    replies = [
        SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", id="t1", name="update_scene",
                                     input={"scene_id": "s3", "scene": scene_body(example, 2, heading="Downhill"), "note": "clearer heading"})],
        ),
        SimpleNamespace(content=[SimpleNamespace(type="text", text="I renamed scene 3 to Downhill.")]),
    ]
    seen = []

    def fake_call(**kwargs):
        seen.append(kwargs)
        return replies.pop(0), llm.Call("claude-test", 100, 50, 10)

    monkeypatch.setattr(llm, "_call", fake_call)
    out = llm.edit_storyboard(board, "clearer heading on scene 3", "s3")
    assert out.board.scenes[2].heading == "Downhill"
    assert out.summary.startswith("I renamed")
    assert out.changes == [{"kind": "updated", "scene_id": "s3", "note": "clearer heading"}]
    assert "scene 3 (id s3)" in seen[0]["messages"][0]["content"]
    assert seen[1]["messages"][-1]["content"][0]["tool_use_id"] == "t1"
    # untouched scenes keep their narration word for word
    assert out.board.scenes[0].narration == example["scenes"][0]["narration"]


def test_edit_route_saves_and_reports_changes(client, owner, example, monkeypatch):
    p = make_written(client, owner, example, monkeypatch)
    edited = Storyboard.model_validate(example)
    edited.scenes[1].heading = "Loss, simply"
    monkeypatch.setattr(llm, "edit_storyboard", lambda *a: llm.EditOutcome(edited, "Simplified scene 2.", [{"kind": "updated", "scene_id": "s2", "note": "simpler"}], [llm.Call("claude-test", 10, 10, 1)]))
    r = client.post(f"/api/projects/{p['id']}/edit", json={"instruction": "simpler", "scene_id": "s2"}, headers=owner)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"] == "Simplified scene 2."
    assert body["project"]["storyboard"]["scenes"][1]["heading"] == "Loss, simply"


def test_write_schema_is_what_claude_gets():
    schema = llm.strict_json_schema(Storyboard)
    assert json.dumps(schema).count('"additionalProperties": false') >= 3
    assert "id" not in llm.EDIT_TOOLS[0]["input_schema"]["properties"]["scene"]["properties"]
