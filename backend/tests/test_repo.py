"""Lessons about a codebase: reading a GitHub repository, grounding citations, the research
loop. GitHub and Claude are faked; nothing here touches the network."""

import io
import json
import tarfile
from types import SimpleNamespace

import pytest

from app import github, grounding, llm
from app.storyboard import Storyboard

APP_PY = "\n".join(f"line {n}" for n in range(1, 41))
FILES = {
    "README.md": "# Tiny\nA tiny app that greets people.\n",
    "app.py": "from greet import hello\n\n\ndef main():\n    print(hello('world'))\n\n\nif __name__ == '__main__':\n    main()\n",
    "greet.py": "def hello(name):\n    return f'Hello, {name}!'\n",
    "long.py": APP_PY,
}


def snapshot() -> github.Snapshot:
    return github.Snapshot("octo", "tiny", "abc123def456", "main", "A tiny app", dict(FILES))


def tarball(files: dict[str, bytes], sha="0123456789abcdef0123456789abcdef01234567") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT, pax_headers={"comment": sha}) as tar:
        for path, data in files.items():
            info = tarfile.TarInfo(f"octo-tiny-0123456/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


# ---------------------------------------------------------------- reading a repository


@pytest.mark.parametrize("text,expected", [
    ("https://github.com/octo/tiny", ("octo", "tiny", None)),
    ("github.com/octo/tiny.git", ("octo", "tiny", None)),
    ("https://github.com/octo/tiny/tree/dev/src", ("octo", "tiny", "dev/src")),
    ("https://github.com/octo/tiny/blob/main/app.py#L3", ("octo", "tiny", "main/app.py")),
    ("octo/tiny", ("octo", "tiny", None)),
])
def test_parse_repo(text, expected):
    assert github.parse_repo(text) == expected


@pytest.mark.parametrize("text", ["", "https://gitlab.com/a/b", "not a repo", "https://github.com/onlyowner"])
def test_parse_repo_rejects(text):
    with pytest.raises(github.RepoError):
        github.parse_repo(text)


def test_keep_skips_vendored_binary_and_lockfiles():
    assert github.keep("src/app.py", 100)
    assert not github.keep("node_modules/x/index.js", 100)
    assert not github.keep("web/package-lock.json", 100)
    assert not github.keep("logo.png", 100)
    assert not github.keep("dist/app.min.js", 100)
    assert not github.keep("big.py", github.MAX_FILE + 1)


def test_download_reads_the_tarball(monkeypatch):
    data = tarball({"app.py": FILES["app.py"].encode(), "node_modules/x.js": b"x", "img.png": b"\x89PNG", "bin.dat": b"\x00\x01"})

    class FakeStream:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_bytes(self):
            yield data

    monkeypatch.setattr(github, "repo_info", lambda o, r: {"full_name": "octo/tiny", "default_branch": "main", "description": "Tiny"})
    monkeypatch.setattr(github.httpx, "stream", lambda *a, **k: FakeStream())
    snap = github.download("octo", "tiny")
    assert snap.sha == "0123456789abcdef0123456789abcdef01234567"
    assert list(snap.files) == ["app.py"]
    assert snap.skipped == 3
    assert snap.url("app.py", 4, 5).endswith("/blob/0123456789abcdef0123456789abcdef01234567/app.py#L4-L5")
    again = github.Snapshot.unpack("octo", "tiny", snap.sha, "main", "Tiny", snap.pack())
    assert again.files == snap.files


def test_tree_read_and_search():
    snap = snapshot()
    assert "app.py  (9 lines)" in github.tree(snap, "")
    out = github.read(snap, "app.py", 4, 5)
    assert "    4  def main():" in out and "    5      print(hello('world'))" in out
    assert "more lines" in github.read(snap, "long.py", 1, 10)
    with pytest.raises(ValueError, match="Did you mean"):
        github.read(snap, "src/greet.py")
    assert "greet.py:1: def hello(name):" in github.search(snap, r"def \w+\(name")
    assert github.search(snap, "nothing-like-this").startswith("No matches")


# ---------------------------------------------------------------- grounding


def repo_board(**source):
    return Storyboard.model_validate({
        "title": "How tiny greets",
        "summary": "Where the greeting comes from.",
        "scenes": [
            {"id": "s1", "layout": "title", "heading": "Tiny", "subheading": "", "items": [], "code": "",
             "source": {"path": "", "start_line": 0, "end_line": 0}, "narration": "This is tiny."},
            {"id": "s2", "layout": "code", "heading": "The greeting", "subheading": "",
             "items": [{"text": "Builds the message", "detail": "", "at": 0, "line": 2}],
             "code": "made up code that is not in the file",
             "source": {"path": "greet.py", "start_line": 1, "end_line": 2, **source},
             "narration": "The hello function builds the message. That's all it does."},
        ],
    })


def test_grounding_fills_code_from_the_file():
    snap = snapshot()
    board = repo_board()
    assert grounding.problems(board, snap) == []
    grounded = grounding.ground(board, snap)
    assert grounded.scenes[1].code == "def hello(name):\n    return f'Hello, {name}!'"


def test_grounding_reports_and_repairs_bad_citations():
    snap = snapshot()
    bad = repo_board(path="nope.py")
    assert "isn't a file" in grounding.problems(bad, snap)[0]
    fixed = grounding.ground(bad, snap)
    assert fixed.scenes[1].layout == "points" and fixed.scenes[1].code == ""  # never shows invented code
    assert "has 2 lines" in grounding.problems(repo_board(end_line=9), snap)[0]
    too_long = repo_board(path="long.py", start_line=1, end_line=30)
    assert "at most 14" in grounding.problems(too_long, snap)[0]
    assert grounding.ground(too_long, snap).scenes[1].source.end_line == 14


# ---------------------------------------------------------------- the research loop


def test_repo_lesson_reads_then_submits_and_fixes_citations(monkeypatch):
    snap = snapshot()
    good = repo_board().model_dump()
    bad = repo_board(end_line=9).model_dump()
    replies = [
        [SimpleNamespace(type="tool_use", id="t1", name="read_file", input={"path": "greet.py", "start_line": 1, "end_line": 0})],
        [SimpleNamespace(type="tool_use", id="t2", name="submit_lesson", input=bad)],
        [SimpleNamespace(type="tool_use", id="t3", name="submit_lesson", input=good)],
    ]
    seen = []

    def fake_call(**kwargs):
        seen.append(json.loads(json.dumps(kwargs["messages"], default=str)))
        return SimpleNamespace(content=replies.pop(0)), llm.Call("claude-test", 1000, 200, 5)

    monkeypatch.setattr(llm, "_call", fake_call)
    progress = []
    board, calls = llm.write_repo_lesson(snap, "How does it greet?", "intro", 2, progress.append)
    assert len(calls) == 3
    assert board.scenes[1].code.startswith("def hello")
    assert progress[0] == "Reading greet.py"
    first = seen[0][0]["content"]
    assert "github.com/octo/tiny" in first and "A tiny app that greets people." in first and "How does it greet?" in first
    # the bad citation went back to Claude as an error to fix
    second_results = seen[2][-1]["content"]
    assert second_results[0]["is_error"] is True and "has 2 lines" in second_results[0]["content"]


def test_repo_write_route(client, monkeypatch):
    owner = {"X-Owner": "repo-route-owner-0123456789"}
    snap = snapshot()
    monkeypatch.setattr(github, "download", lambda o, r, ref=None: snap)
    monkeypatch.setattr(llm, "write_repo_lesson", lambda s, q, lvl, m, progress: (grounding.ground(repo_board(), s), [llm.Call("claude-test", 9000, 2000, 30000)]))
    p = client.post("/api/projects", json={"topic": "How does it greet?", "repo": "https://github.com/octo/tiny"}, headers=owner).json()
    assert p["repo"] == "octo/tiny"
    r = client.post(f"/api/projects/{p['id']}/write", headers=owner)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["repo_sha"] == "abc123def456"
    assert body["storyboard"]["scenes"][1]["code"].startswith("def hello")
    # a hand edit can't put invented code on screen
    board = body["storyboard"]
    board["scenes"][1]["code"] = "print('pwned')"
    saved = client.put(f"/api/projects/{p['id']}/storyboard", json={"storyboard": board}, headers=owner).json()
    assert saved["storyboard"]["scenes"][1]["code"].startswith("def hello")


def test_bad_repo_link_is_explained(client, owner):
    r = client.post("/api/projects", json={"topic": "Anything", "repo": "https://gitlab.com/a/b"}, headers=owner)
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_repo_url"


def test_missing_repo_fails_the_write_honestly(client, monkeypatch):
    owner = {"X-Owner": "missing-repo-owner-0123456"}
    def missing(o, r, ref=None):
        raise github.RepoError("repo_not_found", "github.com/octo/gone doesn't exist, or it's private.", 404)

    monkeypatch.setattr(github, "download", missing)
    p = client.post("/api/projects", json={"topic": "Anything", "repo": "octo/gone"}, headers=owner).json()
    r = client.post(f"/api/projects/{p['id']}/write", headers=owner)
    assert r.status_code == 404
    after = client.get(f"/api/projects/{p['id']}", headers=owner).json()
    assert after["status"] == "failed" and "private" in after["error"]


def test_new_columns_are_added_to_an_old_table(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    from app.db import add_missing_columns

    eng = create_engine(f"sqlite:///{tmp_path}/old.db")
    with eng.begin() as c:
        c.execute(text('CREATE TABLE project (id VARCHAR PRIMARY KEY, owner VARCHAR, topic VARCHAR)'))
    add_missing_columns(eng)
    cols = {c["name"] for c in inspect(eng).get_columns("project")}
    assert {"repo", "repo_sha", "progress", "storyboard"} <= cols


# ---------------------------------------------------------------- fixes from the second review


def test_a_repo_lesson_counts_as_one_lesson_however_many_requests(client, monkeypatch):
    monkeypatch.setenv("LIMIT_WRITES_PER_BROWSER", "2")
    owner = {"X-Owner": "many-requests-owner-01234567"}
    snap = snapshot()
    monkeypatch.setattr(github, "head_sha", lambda *a: None)
    monkeypatch.setattr(github, "download", lambda o, r, ref=None: snap)
    many = [llm.Call("claude-test", 1000, 100, 10) for _ in range(30)]
    monkeypatch.setattr(llm, "write_repo_lesson", lambda s, q, lvl, m, progress: (grounding.ground(repo_board(), s), many))
    first = client.post("/api/projects", json={"topic": "One", "repo": "octo/tiny"}, headers=owner).json()
    assert client.post(f"/api/projects/{first['id']}/write", headers=owner).status_code == 200
    second = client.post("/api/projects", json={"topic": "Two", "repo": "octo/tiny"}, headers=owner).json()
    assert client.post(f"/api/projects/{second['id']}/write", headers=owner).status_code == 200
    usage = client.get(f"/api/projects/{first['id']}/usage", headers=owner).json()["calls"]
    assert len(usage) == 1 and usage[0]["requests"] == 30 and usage[0]["input_tokens"] == 30000


def test_lessons_saved_before_sources_existed_still_load():
    old = json.loads(json.dumps(repo_board().model_dump()))
    for scene in old["scenes"]:
        scene.pop("source")
        for item in scene["items"]:
            item.pop("line")
    board = Storyboard.model_validate(old)
    assert board.scenes[1].source.path == "" and board.scenes[1].items[0].line == 0
    assert "default" not in json.dumps(llm.strict_json_schema(Storyboard))


def test_repo_name_is_stored_the_way_github_spells_it(client, monkeypatch):
    owner = {"X-Owner": "case-owner-0123456789abcd"}
    snap = snapshot()  # GitHub calls it octo/tiny
    monkeypatch.setattr(github, "head_sha", lambda *a: None)
    monkeypatch.setattr(github, "download", lambda o, r, ref=None: snap)
    monkeypatch.setattr(llm, "write_repo_lesson", lambda s, q, lvl, m, progress: (grounding.ground(repo_board(), s), [llm.Call("c", 1, 1, 1)]))
    p = client.post("/api/projects", json={"topic": "Case", "repo": "github.com/Octo/Tiny"}, headers=owner).json()
    written = client.post(f"/api/projects/{p['id']}/write", headers=owner).json()
    assert written["repo"] == "octo/tiny"
    board = written["storyboard"]
    board["scenes"][1]["code"] = "print('invented')"
    saved = client.put(f"/api/projects/{p['id']}/storyboard", json={"storyboard": board}, headers=owner).json()
    assert saved["storyboard"]["scenes"][1]["code"].startswith("def hello")


def test_a_half_typed_source_survives_a_hand_save():
    snap = snapshot()
    board = repo_board(path="gre", start_line=0, end_line=0)  # mid-typing
    kept = grounding.ground(board, snap, hand=True)
    assert kept.scenes[1].layout == "code" and kept.scenes[1].source.path == "gre" and kept.scenes[1].code == ""
    assert grounding.ground(board, snap).scenes[1].layout == "points"  # Claude's output still gets repaired


def test_progress_is_a_heartbeat(client):
    from app.main import progress_writer
    from app.models import Project, now
    from datetime import timedelta
    from sqlmodel import Session

    from app.db import engine

    owner = {"X-Owner": "heartbeat-owner-0123456789"}
    p = client.post("/api/projects", json={"topic": "Heartbeat", "repo": "octo/tiny"}, headers=owner).json()
    with Session(engine) as s:
        row = s.get(Project, p["id"])
        row.status, row.updated_at = "writing", now() - timedelta(minutes=30)
        s.add(row)
        s.commit()
    progress_writer(p["id"])("Reading app.py")
    after = client.get(f"/api/projects/{p['id']}", headers=owner).json()
    assert after["status"] == "writing" and after["progress"][-1] == "Reading app.py"



def test_a_long_write_keeps_every_step(client):
    """The waiting screen counts files and searches from these lines, so none may drop off."""
    from app.main import progress_writer

    owner = {"X-Owner": "long-trace-owner-0123456789"}
    p = client.post("/api/projects", json={"topic": "Long trace", "repo": "octo/tiny"}, headers=owner).json()
    write = progress_writer(p["id"])
    for i in range(60):
        write(f"Reading file{i}.py")
    progress = client.get(f"/api/projects/{p['id']}", headers=owner).json()["progress"]
    assert len(progress) == 60 and progress[0] == "Reading file0.py"

def test_a_pathological_search_stops_instead_of_hanging(monkeypatch):
    import time

    monkeypatch.setattr(github, "SEARCH_SECONDS", 0.3)
    snap = github.Snapshot("o", "r", "s", "main", "", {"x.txt": "a" * 40 + "b"})
    started = time.monotonic()
    out = github.search(snap, r"(a|aa)+$")
    assert time.monotonic() - started < 3
    assert "took too long" in out or out.startswith("No matches")


def test_a_broken_archive_is_a_readable_error(monkeypatch):
    data = tarball({"app.py": b"print(1)\n"})[:-40]  # truncated gzip

    class FakeStream:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_bytes(self):
            yield data

    monkeypatch.setattr(github, "repo_info", lambda o, r: {})
    monkeypatch.setattr(github.httpx, "stream", lambda *a, **k: FakeStream())
    with pytest.raises(github.RepoError) as e:
        github.download("octo", "tiny")
    assert e.value.code == "repo_unreadable"


def test_an_unplanned_failure_ends_the_write(client, monkeypatch):
    owner = {"X-Owner": "unplanned-owner-0123456789"}
    monkeypatch.setattr(github, "head_sha", lambda *a: None)

    def boom(o, r, ref=None):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(github, "download", boom)
    p = client.post("/api/projects", json={"topic": "Boom", "repo": "octo/tiny"}, headers=owner).json()
    r = client.post(f"/api/projects/{p['id']}/write", headers=owner)
    assert r.status_code == 500 and r.json()["error"]["code"] == "write_failed"
    assert client.get(f"/api/projects/{p['id']}", headers=owner).json()["status"] == "failed"


def test_a_stored_commit_is_reused_without_downloading(client, monkeypatch):
    from sqlmodel import Session

    from app import main
    from app.db import engine

    snap = github.Snapshot("octo", "reuse", "f" * 40, "main", "", dict(FILES))
    monkeypatch.setattr(github, "download", lambda o, r, ref=None: snap)
    with Session(engine) as s:
        main.fetch_snapshot(s, "octo/reuse")  # stores it
    main._snapshots.clear()

    def no_download(*a, **k):
        raise AssertionError("downloaded again")

    monkeypatch.setattr(github, "download", no_download)
    monkeypatch.setattr(github, "head_sha", lambda o, r, ref: "f" * 40)
    with Session(engine) as s:
        assert main.fetch_snapshot(s, "Octo/Reuse").sha == "f" * 40


def test_a_branch_link_keeps_its_branch(client):
    owner = {"X-Owner": "branch-owner-0123456789ab"}
    p = client.post("/api/projects", json={"topic": "Branch", "repo": "https://github.com/octo/tiny/tree/dev"}, headers=owner).json()
    assert p["repo"] == "octo/tiny" and p["repo_ref"] == "dev"


def test_archive_caps(monkeypatch):
    data = tarball({f"f{i}.py": b"x = 1\n" for i in range(5)})

    class FakeStream:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_bytes(self):
            yield data

    monkeypatch.setattr(github, "repo_info", lambda o, r: {})
    monkeypatch.setattr(github.httpx, "stream", lambda *a, **k: FakeStream())
    monkeypatch.setattr(github, "MAX_MEMBERS", 3)
    with pytest.raises(github.RepoError) as e:
        github.download("octo", "tiny")
    assert e.value.code == "repo_too_big"



def test_branch_names_with_slashes_are_resolved(monkeypatch):
    branches = {"feature/login": "a" * 40, "main": "b" * 40}
    monkeypatch.setattr(github, "lookup_sha", lambda o, r, ref: branches.get(ref))
    assert github.resolve_ref("o", "r", "feature/login/src/app.py") == "feature/login"
    assert github.resolve_ref("o", "r", "main/app.py") == "main"
    assert github.resolve_ref("o", "r", "dev") == "dev"
    with pytest.raises(github.RepoError):
        github.resolve_ref("o", "r", "nope/also/nope")


def test_a_failed_rewrite_keeps_the_old_commit(client, monkeypatch):
    owner = {"X-Owner": "rewrite-owner-0123456789ab"}
    first = github.Snapshot("octo", "tiny", "1" * 40, "main", "", dict(FILES))
    monkeypatch.setattr(github, "head_sha", lambda *a: None)
    monkeypatch.setattr(github, "download", lambda o, r, ref=None: first)
    monkeypatch.setattr(llm, "write_repo_lesson", lambda s, q, lvl, m, progress: (grounding.ground(repo_board(), s), [llm.Call("c", 1, 1, 1)]))
    p = client.post("/api/projects", json={"topic": "Rewrite", "repo": "octo/tiny"}, headers=owner).json()
    assert client.post(f"/api/projects/{p['id']}/write", headers=owner).json()["repo_sha"] == "1" * 40

    second = github.Snapshot("octo", "tiny", "2" * 40, "main", "", {**FILES, "greet.py": "x = 1\n"})
    monkeypatch.setattr(github, "download", lambda o, r, ref=None: second)

    def fails(*a, **k):
        raise llm.AIError("ai_busy", "Busy.", 429)

    monkeypatch.setattr(llm, "write_repo_lesson", fails)
    from sqlmodel import Session

    from app.db import engine
    from app.models import Project

    with Session(engine) as s:  # let it be rewritten
        row = s.get(Project, p["id"])
        row.status = "failed"
        s.add(row)
        s.commit()
    assert client.post(f"/api/projects/{p['id']}/write", headers=owner).status_code == 429
    after = client.get(f"/api/projects/{p['id']}", headers=owner).json()
    assert after["repo_sha"] == "1" * 40  # still the commit its storyboard was written from


def test_late_source_files_displace_early_docs(monkeypatch):
    files = {f"docs/page{i}.md": b"d" * 400 for i in range(5)}
    files["src/main.py"] = b"print('the real code')\n"
    data = tarball(files)

    class FakeStream:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_bytes(self):
            yield data

    monkeypatch.setattr(github, "repo_info", lambda o, r: {})
    monkeypatch.setattr(github.httpx, "stream", lambda *a, **k: FakeStream())
    monkeypatch.setattr(github, "MAX_CANDIDATES", 1300)  # room for about three docs
    snap = github.download("octo", "tiny")
    assert "src/main.py" in snap.files and snap.truncated


def test_topic_lessons_are_told_to_write_their_code():
    from app.storyboard import LAYOUTS

    assert "Otherwise write the code" in LAYOUTS["code"]



def test_a_github_outage_is_not_a_missing_branch(monkeypatch):
    def down(o, r, ref):
        raise github.RepoError("github_unavailable", "GitHub couldn't answer just now.", 503)

    monkeypatch.setattr(github, "lookup_sha", down)
    with pytest.raises(github.RepoError) as e:
        github.resolve_ref("o", "r", "main/app.py")
    assert e.value.code == "github_unavailable" and e.value.status == 503


def test_a_file_link_reuses_the_stored_commit(client, monkeypatch):
    from sqlmodel import Session

    from app import main
    from app.db import engine

    snap = github.Snapshot("octo", "filelink", "e" * 40, "main", "", dict(FILES))
    monkeypatch.setattr(github, "lookup_sha", lambda o, r, ref: "e" * 40 if ref == "main" else None)
    monkeypatch.setattr(github, "download", lambda o, r, ref=None: snap)
    with Session(engine) as s:
        main.fetch_snapshot(s, "octo/filelink", "main")
    main._snapshots.clear()

    def no_download(*a, **k):
        raise AssertionError("downloaded again")

    monkeypatch.setattr(github, "download", no_download)
    with Session(engine) as s:
        assert main.fetch_snapshot(s, "octo/filelink", "main/app.py").sha == "e" * 40


def test_mixed_models_are_priced_per_request(client, monkeypatch):
    owner = {"X-Owner": "mixed-model-owner-01234567"}
    snap = snapshot()
    monkeypatch.setattr(github, "head_sha", lambda *a: None)
    monkeypatch.setattr(github, "download", lambda o, r, ref=None: snap)
    calls = [llm.Call("claude-opus-5-5", 1_000_000, 0, 1), llm.Call("claude-haiku-5-5", 1_000_000, 0, 1)]
    monkeypatch.setattr(llm, "write_repo_lesson", lambda s, q, lvl, m, progress: (grounding.ground(repo_board(), s), calls))
    p = client.post("/api/projects", json={"topic": "Mixed", "repo": "octo/tiny"}, headers=owner).json()
    client.post(f"/api/projects/{p['id']}/write", headers=owner)
    usage = client.get(f"/api/projects/{p['id']}/usage", headers=owner).json()["calls"]
    assert usage[0]["cost_usd"] == 4.1  # $4 for Opus plus $0.10 for Haiku, not $0.20
