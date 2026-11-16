"""Lessons made by someone's own Claude (the /lesson skill): imported, claimed, never
charged to the site."""

import json

from app import secrets_scan


def board(example, **scene_patch):
    b = json.loads(json.dumps(example))
    b["scenes"][5].update(scene_patch)
    return b


def imported(client, example, ip="203.0.113.7", **extra):
    r = client.post("/api/import", json={"storyboard": example, "question": "How does it work?", **extra},
                    headers={"X-Forwarded-For": ip})
    return r


def test_import_returns_a_one_time_claim_link(client, example, owner, other):
    r = imported(client, example)
    assert r.status_code == 201, r.text
    body = r.json()
    assert "/l/" in body["url"] and "?claim=" in body["url"]
    pid, token = body["id"], body["url"].split("claim=")[1]

    before = client.get(f"/api/projects/{pid}", headers=owner).json()
    assert before["is_owner"] is False and before["origin"] == "local"

    claimed = client.post(f"/api/projects/{pid}/claim", json={"token": token}, headers=owner)
    assert claimed.status_code == 200 and claimed.json()["is_owner"] is True
    assert pid in [p["id"] for p in client.get("/api/projects", headers=owner).json()["projects"]]

    # the link works once
    again = client.post(f"/api/projects/{pid}/claim", json={"token": token}, headers=other)
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_claimed"


def test_a_wrong_token_claims_nothing(client, example, other):
    pid = imported(client, example).json()["id"]
    r = client.post(f"/api/projects/{pid}/claim", json={"token": "not-the-right-token-123"}, headers=other)
    assert r.status_code == 403
    assert client.get(f"/api/projects/{pid}", headers=other).json()["is_owner"] is False


def test_nobody_can_edit_an_unclaimed_lesson(client, example, owner):
    pid = imported(client, example).json()["id"]
    r = client.put(f"/api/projects/{pid}/storyboard", json={"storyboard": example}, headers=owner)
    assert r.status_code == 403


def test_secrets_are_refused(client, example):
    leaked = board(example, code='API_KEY = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"')
    r = imported(client, leaked)
    assert r.status_code == 422 and r.json()["error"]["code"] == "looks_like_a_secret"
    assert "an Anthropic key" in r.json()["error"]["message"]


def test_oversized_scenes_are_refused(client, example):
    r = imported(client, board(example, code="\n".join(f"line {i}" for i in range(30))))
    assert r.status_code == 422 and r.json()["error"]["code"] == "too_big"


def test_imported_lessons_get_no_server_ai_edits(client, example, owner):
    body = imported(client, example).json()
    client.post(f"/api/projects/{body['id']}/claim", json={"token": body["url"].split("claim=")[1]}, headers=owner)
    r = client.post(f"/api/projects/{body['id']}/edit", json={"instruction": "simpler"}, headers=owner)
    assert r.status_code == 409 and r.json()["error"]["code"] == "edit_where_made"


def test_imports_are_limited_per_address(client, example, monkeypatch):
    monkeypatch.setenv("LIMIT_IMPORTS_PER_ADDRESS", "2")
    ip = "198.51.100.42"
    assert imported(client, example, ip=ip).status_code == 201
    assert imported(client, example, ip=ip).status_code == 201
    r = imported(client, example, ip=ip)
    assert r.status_code == 429 and r.json()["error"]["code"] == "limit"
    assert imported(client, example, ip="198.51.100.43").status_code == 201  # someone else


def test_repo_links_need_a_full_commit(client, example):
    r = imported(client, example, repo="octo/tiny", sha="abc")
    assert r.status_code == 422
    ok = imported(client, example, repo="octo/tiny", sha="a" * 40).json()
    got = client.get(f"/api/projects/{ok['id']}").json()
    assert got["repo"] == "octo/tiny" and got["repo_sha"] == "a" * 40


def test_secret_scanner():
    assert secrets_scan.find_secret("token = 'ghp_" + "a" * 36 + "'") == "a GitHub token"
    assert secrets_scan.find_secret("-----BEGIN RSA PRIVATE KEY-----") == "a private key"
    assert secrets_scan.find_secret("postgres://user:hunter2hunter2@db/app") == "a password or key in a URL"
    assert secrets_scan.find_secret("def get_api_key(): return os.environ['API_KEY']") is None
    assert secrets_scan.find_secret("The token is checked before every request.") is None


def test_title_summary_and_question_are_scanned_too(client, example):
    leaked = json.loads(json.dumps(example))
    leaked["summary"] = "Uses sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789 to call Claude."
    r = imported(client, leaked)
    assert r.status_code == 422 and "The summary" in r.json()["error"]["message"]
    r = client.post("/api/import", json={"storyboard": example, "question": "why ghp_" + "a" * 36}, headers={"X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 422 and "The question" in r.json()["error"]["message"]


def test_the_size_limit_counts_bytes_even_without_a_length_header(client, example):
    big = json.loads(json.dumps(example))
    big["scenes"][0]["narration"] = "word " * 80_000
    body = json.dumps({"storyboard": big, "question": "Too big?"}).encode()

    def chunks():
        for i in range(0, len(body), 16_384):
            yield body[i : i + 16_384]

    r = client.post("/api/import", content=chunks(), headers={"Content-Type": "application/json", "X-Forwarded-For": "203.0.113.10"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_big"


def test_hand_saves_keep_a_local_lessons_code(client, example, owner, monkeypatch):
    from app import github, main

    body = imported(client, example, repo="octo/tiny", sha="b" * 40).json()
    client.post(f"/api/projects/{body['id']}/claim", json={"token": body["url"].split("claim=")[1]}, headers=owner)
    # another lesson cached a trimmed copy of the same commit
    main.remember(github.Snapshot("octo", "tiny", "b" * 40, "main", "", {"README.md": "x\n"}))
    saved = client.put(f"/api/projects/{body['id']}/storyboard", json={"storyboard": example}, headers=owner).json()
    assert saved["storyboard"]["scenes"][5]["code"] == example["scenes"][5]["code"]
