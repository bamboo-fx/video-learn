"""The /lesson skill's helper (skill/lesson/lesson.py), run against throwaway git repositories."""

import importlib.util
import io
import json
import os
import pathlib
import subprocess
from contextlib import redirect_stdout

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("lesson", ROOT / "skill" / "lesson" / "lesson.py")
lesson = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lesson)

AUTH = "\n".join([
    "import hashlib",
    "",
    "",
    "def check_password(user, given):",
    "    digest = hashlib.sha256(given.encode()).hexdigest()",
    "    return digest == user.password_hash",
    "",
])


def sh(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "app"
    (r / "src").mkdir(parents=True)
    (r / "src" / "auth.py").write_text(AUTH)
    (r / "README.md").write_text("# App\nLogs people in.\n")
    (r / ".env").write_text("SECRET_KEY=hunter2hunter2hunter2\n")
    (r / "config").mkdir()
    (r / "config" / "credentials.json").write_text('{"k": 1}\n')
    (r / "src" / "leaky.py").write_text('API_KEY = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz012345"\nprint(1)\n')
    (r / "node_modules").mkdir()
    (r / "node_modules" / "x.js").write_text("x\n")
    (r / ".gitignore").write_text("node_modules/\n")
    outside = tmp_path / "outside.txt"
    outside.write_text("private\n")
    (r / "src" / "link.py").symlink_to(outside)
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    sh(r, "git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    monkeypatch.chdir(r)
    return r


def run(*argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = lesson.main(list(argv))
    return code, out.getvalue()


def storyboard(**src):
    return {
        "title": "How login works",
        "summary": "Where passwords are checked.",
        "scenes": [
            {"id": "s1", "layout": "title", "heading": "Login", "subheading": "", "items": [], "narration": "This is login."},
            {"id": "s2", "layout": "code", "heading": "Checking", "subheading": "",
             "items": [{"text": "Hashes what was typed", "detail": "", "at": 0, "line": 5}],
             "code": "made up code", "source": {"path": "src/auth.py", "start_line": 4, "end_line": 6, **src},
             "narration": "It hashes the password. Then it compares."},
        ],
    }


def write(repo, board):
    d = repo / ".video-learn"
    d.mkdir(exist_ok=True)
    (d / "storyboard.json").write_text(json.dumps(board))
    return str(d / "storyboard.json")


def test_scan_hides_secrets_dependencies_and_escapes(repo):
    files, no = lesson.allowed_files(repo)
    assert "src/auth.py" in files and "README.md" in files
    assert no[".env"] == "may hold secrets"
    assert no["config/credentials.json"] == "may hold secrets"
    assert no["src/link.py"] == "points outside the repository"
    assert not any(p.startswith("node_modules/") for p in files)
    code, out = run("scan")
    assert code == 0 and ".env" in out and "Never read or cite" in out
    assert ".video-learn/" in (repo / ".git" / "info" / "exclude").read_text()


def test_check_fills_code_from_the_file(repo):
    path = write(repo, storyboard())
    board, problems, _, _ = lesson.load_and_ground(path)
    assert problems == []
    assert board["scenes"][1]["code"] == "def check_password(user, given):\n    digest = hashlib.sha256(given.encode()).hexdigest()\n    return digest == user.password_hash"
    assert run("check", path)[0] == 0


@pytest.mark.parametrize("src,expect", [
    ({"path": ".env", "start_line": 1, "end_line": 1}, "may hold secrets"),
    ({"path": "src/nope.py"}, "isn't a file Video Learn may read"),
    ({"end_line": 99}, "which has 6 lines"),
    ({"path": "src/leaky.py", "start_line": 1, "end_line": 2}, "an Anthropic key"),
    ({"path": "src/link.py", "start_line": 1, "end_line": 1}, "isn't a file Video Learn may read"),
])
def test_bad_citations_are_refused(repo, src, expect):
    path = write(repo, storyboard(**src))
    code, out = run("check", path)
    assert code == 2 and expect in out


def test_publish_asks_first_and_sends_only_the_storyboard(repo, monkeypatch):
    path = write(repo, storyboard())
    code, out = run("publish", path)
    assert code == 3 and "Not uploaded" in out and "src/auth.py  (lines 4-6)" in out
    assert run("publish", path, "--dry-run")[0] == 0

    sent = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        sent["url"], sent["body"] = req.full_url, json.loads(req.data)
        return Resp(json.dumps({"url": "https://example.test/l/abc?claim=t", "id": "abc"}).encode())

    monkeypatch.setattr(lesson.urllib.request, "urlopen", fake_urlopen)
    code, out = run("publish", path, "--yes", "--question", "How does login work?")
    assert code == 0 and "https://example.test/l/abc?claim=t" in out
    assert sent["url"].endswith("/api/import")
    body = sent["body"]
    assert set(body) == {"storyboard", "question", "repo", "sha", "client"}
    assert body["storyboard"]["scenes"][1]["code"].startswith("def check_password")
    assert "SECRET_KEY" not in json.dumps(body) and "hunter2" not in json.dumps(body)
    assert body["repo"] == "" and body["sha"] == ""  # no GitHub remote: no links


def test_diff_lists_what_changed(repo):
    sh(repo, "git", "switch", "-qc", "feature")
    (repo / "src" / "auth.py").write_text(AUTH + "\n\ndef logout(user):\n    user.session = None\n")
    (repo / "src" / "new.py").write_text("x = 1\n")
    code, out = run("scan", "--diff", "main")
    assert code == 0
    changed = out.split("committed or not:")[1]
    assert "src/auth.py" in changed and "src/new.py" in changed


def test_paths_keep_their_leading_dot():
    assert lesson.clean_path("./.github/workflows/ci.yml") == ".github/workflows/ci.yml"
    assert lesson.clean_path("/src/app.py") == "src/app.py"
