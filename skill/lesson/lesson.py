#!/usr/bin/env python3
"""The /lesson skill's helper: the safety work on your own machine.

Claude Code researches your code and writes a lesson as a storyboard (JSON). This script
decides which files may be read, fills every code scene with the exact lines from your
files, refuses secrets, and, only when you say yes, uploads the storyboard to Video Learn.
Your repository never leaves your computer: only the lines the lesson shows do.

    python3 lesson.py scan [--diff BASE]       which files may be read (and what changed)
    python3 lesson.py check FILE               validate a storyboard and fill its code
    python3 lesson.py publish FILE --dry-run   show exactly what would be uploaded
    python3 lesson.py publish FILE --yes       upload it and print the lesson's link

Standard library only, so there is nothing to install.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "1"
SERVER = os.environ.get("VIDEO_LEARN_URL", "https://web-production-77637c10.up.railway.app").rstrip("/")

LAYOUTS = {"title", "points", "steps", "compare", "definition", "example", "code", "flow", "summary"}
MAX_SCENES, MAX_ITEMS, MAX_CODE_LINES = 12, 5, 14
MAX_FILE_BYTES = 512 * 1024

SKIP_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", "out", ".next", ".nuxt", "target", "__pycache__",
    ".venv", "venv", "env", ".tox", ".mypy_cache", ".pytest_cache", "coverage", ".idea", ".vscode",
    ".terraform", ".cache", "site-packages", ".video-learn",
}
# Never read, never cite: files whose whole job is holding secrets or credentials.
DENY = [
    ".env", ".env.*", "*.env", ".envrc", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.kdbx",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*", "*.ppk", ".npmrc", ".pypirc", ".netrc", ".git-credentials",
    ".htpasswd", "credentials", "credentials.*", "*credential*", "*secret*", "*.tfstate", "*.tfstate.*",
    "*.tfvars", "service-account*.json", "*-sa.json", "*.sqlite", "*.sqlite3", "*.db", ".dockercfg",
    "docker-config.json", "kubeconfig", "*.kubeconfig",
]
BINARY = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".pdf", ".zip", ".gz", ".tar", ".jar", ".woff",
    ".woff2", ".ttf", ".otf", ".mp3", ".mp4", ".mov", ".wav", ".so", ".dylib", ".dll", ".exe", ".bin", ".pyc",
    ".class", ".o", ".a", ".min.js", ".min.css", ".map", ".lock", ".lockb",
)

SECRETS = [
    ("a private key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("an AWS access key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("a GitHub token", r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    ("an Anthropic key", r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    ("an OpenAI key", r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}"),
    ("a Stripe key", r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{20,}"),
    ("a Slack token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    ("a Google API key", r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ("a JSON web token", r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    ("a password or key in a URL", r"(?i)[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]{6,}@"),
    ("a hard-coded secret", r"(?i)\b(?:api[_-]?key|secret|token|passw(?:or)?d|private[_-]?key|access[_-]?key)\b\s*[:=]\s*['\"][^'\"\s]{12,}['\"]"),
]
SECRET_RES = [(label, re.compile(rx)) for label, rx in SECRETS]


class Problem(Exception):
    pass


# ---------------------------------------------------------------- which files may be read


def git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if out.returncode != 0:
        raise Problem(out.stderr.strip() or f"git {' '.join(args)} failed")
    return out.stdout


def repo_root() -> Path:
    try:
        return Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    except (Problem, FileNotFoundError):
        return Path.cwd()


def blocked(rel: str) -> str | None:
    """Why a path may not be read, or None."""
    parts = rel.split("/")
    if any(p in SKIP_DIRS for p in parts[:-1]):
        return "dependency or build folder"
    name = parts[-1].lower()
    if any(fnmatch.fnmatch(name, pat) for pat in DENY):
        return "may hold secrets"
    if name.endswith(BINARY):
        return "not text"
    return None


def candidate_files(root: Path) -> list[str]:
    """Tracked and untracked files that .gitignore doesn't exclude (or a plain walk without git)."""
    try:
        listed = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
        return sorted({p for p in listed.split("\0") if p})
    except (Problem, FileNotFoundError):
        out = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for f in filenames:
                out.append(str((Path(dirpath) / f).relative_to(root)).replace(os.sep, "/"))
        return sorted(out)


def inside(root: Path, rel: str) -> Path | None:
    """The real file, only if it stays inside the repository (no symlinks out, no ../)."""
    try:
        path = (root / rel).resolve()
        path.relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    return path if path.is_file() else None


def allowed_files(root: Path) -> tuple[dict[str, Path], dict[str, str]]:
    ok: dict[str, Path] = {}
    no: dict[str, str] = {}
    for rel in candidate_files(root):
        if why := blocked(rel):
            no[rel] = why
            continue
        path = inside(root, rel)
        if path is None:
            no[rel] = "points outside the repository"
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            no[rel] = "too big"
            continue
        ok[rel] = path
    return ok, no


def read_lines(path: Path) -> list[str] | None:
    raw = path.read_bytes()
    if b"\0" in raw[:4096]:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    text = text.replace("\r\n", "\n")
    return (text[:-1] if text.endswith("\n") else text).split("\n")


def keep_out_of_git(root: Path) -> None:
    """The storyboard draft lives in .video-learn/; keep it out of commits (locally only)."""
    exclude = root / ".git" / "info" / "exclude"
    if exclude.parent.is_dir():
        text = exclude.read_text() if exclude.exists() else ""
        if ".video-learn/" not in text.split():
            exclude.write_text(text + ("" if text.endswith("\n") or not text else "\n") + ".video-learn/\n")


# ---------------------------------------------------------------- the storyboard


def normalize(raw: dict) -> dict:
    """Validate the shape and fill the fields Claude may leave out."""
    if not isinstance(raw, dict):
        raise Problem("The storyboard must be a JSON object.")
    scenes = raw.get("scenes")
    if not isinstance(raw.get("title"), str) or not raw["title"].strip():
        raise Problem("The storyboard needs a title.")
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= MAX_SCENES:
        raise Problem(f"The storyboard needs 1 to {MAX_SCENES} scenes.")
    out_scenes = []
    for n, s in enumerate(scenes, 1):
        if not isinstance(s, dict):
            raise Problem(f"Scene {n} must be an object.")
        layout = s.get("layout")
        if layout not in LAYOUTS:
            raise Problem(f"Scene {n} has layout {layout!r}; use one of {', '.join(sorted(LAYOUTS))}.")
        items = s.get("items") or []
        if not isinstance(items, list) or len(items) > MAX_ITEMS:
            raise Problem(f"Scene {n} can have at most {MAX_ITEMS} items.")
        src = s.get("source") or {}
        out_scenes.append({
            "id": str(s.get("id") or f"s{n}"),
            "layout": layout,
            "heading": str(s.get("heading") or ""),
            "subheading": str(s.get("subheading") or ""),
            "items": [
                {"text": str(it.get("text") or ""), "detail": str(it.get("detail") or ""),
                 "at": max(0, int(it.get("at") or 0)), "line": max(0, int(it.get("line") or 0))}
                for it in items if isinstance(it, dict)
            ],
            "code": "",  # always filled from the file below, never taken from the draft
            "source": {"path": clean_path(str(src.get("path") or "")),
                       "start_line": max(0, int(src.get("start_line") or 0)),
                       "end_line": max(0, int(src.get("end_line") or 0))},
            "narration": str(s.get("narration") or ""),
        })
        if not out_scenes[-1]["narration"].strip():
            raise Problem(f"Scene {n} has no narration.")
    return {"title": raw["title"].strip(), "summary": str(raw.get("summary") or ""), "scenes": out_scenes}


def clean_path(p: str) -> str:
    """'./src/app.py' or '/src/app.py' -> 'src/app.py' (a leading dot in '.github/' stays)."""
    p = p.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def ground(board: dict, root: Path, files: dict[str, Path]) -> tuple[dict, list[str]]:
    """Fill code scenes with the real lines and list every citation that doesn't hold."""
    problems: list[str] = []
    for n, s in enumerate(board["scenes"], 1):
        src = s["source"]
        where = f"Scene {n} ({s['id']})"
        if not src["path"]:
            if s["layout"] == "code":
                problems.append(f"{where} is a code scene with no source. Set source to a file and line range.")
            continue
        if src["path"] not in files:
            reason = "isn't a file Video Learn may read" + (" (it may hold secrets)" if blocked(src["path"]) == "may hold secrets" else "")
            problems.append(f"{where} cites {src['path']!r}, which {reason}.")
            continue
        lines = read_lines(files[src["path"]])
        if lines is None:
            problems.append(f"{where} cites {src['path']!r}, which isn't a text file.")
            continue
        a, b = src["start_line"], src["end_line"]
        if not 1 <= a <= b <= len(lines):
            problems.append(f"{where} cites lines {a}-{b} of {src['path']}, which has {len(lines)} lines.")
            continue
        shown = lines[a - 1 : b]
        if s["layout"] == "code":
            if b - a + 1 > MAX_CODE_LINES:
                problems.append(f"{where} shows {b - a + 1} lines; a code scene shows at most {MAX_CODE_LINES}.")
                continue
            for k, it in enumerate(s["items"], 1):
                if it["line"] and not a <= it["line"] <= b:
                    problems.append(f"{where}, item {k} points at line {it['line']}, outside lines {a}-{b}.")
            s["code"] = "\n".join(shown)
        else:
            for it in s["items"]:
                it["line"] = 0
        for label, rx in SECRET_RES:
            if rx.search("\n".join(shown)):
                problems.append(f"{where} cites lines of {src['path']} that seem to contain {label}. Cite different lines.")
                break
    return board, problems


def repo_link(root: Path, cited: set[str]) -> tuple[str, str]:
    """The public GitHub repository and commit, only when the cited files are exactly what's
    pushed there (so "Open on GitHub" shows the same lines). Otherwise no links."""
    try:
        url = git(root, "remote", "get-url", "origin").strip()
        m = re.search(r"github\.com[:/]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?$", url)
        sha = git(root, "rev-parse", "HEAD").strip()
        pushed = git(root, "branch", "-r", "--contains", "HEAD").strip()
        changed = git(root, "status", "--porcelain", "--", *sorted(cited)).strip() if cited else ""
    except (Problem, FileNotFoundError):
        return "", ""
    if not m or not pushed or changed or not re.fullmatch(r"[0-9a-f]{40}", sha):
        return "", ""
    return f"{m.group(1)}/{m.group(2)}", sha


# ---------------------------------------------------------------- commands


def cmd_scan(args: argparse.Namespace) -> int:
    root = repo_root()
    files, no = allowed_files(root)
    keep_out_of_git(root)
    print(f"Repository: {root}")
    print(f"{len(files)} files may be read. {len(no)} are off limits.")
    secret_like = sorted(p for p, why in no.items() if why == "may hold secrets")
    if secret_like:
        print("Never read or cite these (they may hold secrets): " + ", ".join(secret_like[:30]) + (" ..." if len(secret_like) > 30 else ""))
    print("\nFiles you may read:")
    for rel in list(files)[:400]:
        print("  " + rel)
    if len(files) > 400:
        print(f"  ... and {len(files) - 400} more (use Glob to find them)")
    if args.diff is not None:
        base = args.diff or default_base(root)
        merge_base = git(root, "merge-base", base, "HEAD").strip()
        names = [n for n in git(root, "diff", "--name-only", merge_base).split("\n") if n and n in files]
        untracked = [n for n in git(root, "ls-files", "--others", "--exclude-standard").split("\n") if n and n in files]
        print(f"\nChanged since {base} (merge base {merge_base[:7]}), committed or not:")
        for n in names + [u for u in untracked if u not in names]:
            print("  " + n)
        print(f"\nSee each change with: git diff {merge_base[:12]} -- <file>")
    return 0


def default_base(root: Path) -> str:
    for ref in ("origin/HEAD", "origin/main", "origin/master", "main", "master"):
        try:
            git(root, "rev-parse", "--verify", "--quiet", ref)
            return ref
        except Problem:
            continue
    raise Problem("Couldn't find a base branch. Pass one: scan --diff main")


def load_and_ground(path: str) -> tuple[dict, list[str], Path, dict[str, Path]]:
    root = repo_root()
    files, _ = allowed_files(root)
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise Problem(f"Couldn't read {path}: {exc}") from exc
    board, problems = ground(normalize(raw), root, files)
    return board, problems, root, files


def cmd_check(args: argparse.Namespace) -> int:
    board, problems, _, _ = load_and_ground(args.file)
    if problems:
        print("Fix these, then check again:\n- " + "\n- ".join(problems))
        return 2
    cited = sorted({s["source"]["path"] for s in board["scenes"] if s["source"]["path"]})
    print(f"OK: {len(board['scenes'])} scenes, citing {len(cited)} files. Code scenes were filled from the files.")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    board, problems, root, _ = load_and_ground(args.file)
    if problems:
        print("Not uploaded. Fix these first:\n- " + "\n- ".join(problems))
        return 2
    cited = {s["source"]["path"] for s in board["scenes"] if s["source"]["path"]}
    repo, sha = repo_link(root, cited)
    payload = {"storyboard": board, "question": args.question or board["title"], "repo": repo, "sha": sha,
               "client": f"lesson-skill/{VERSION}"}
    body = json.dumps(payload).encode()
    shown = sum(len(s["code"].split("\n")) for s in board["scenes"] if s["code"])
    print(f"Would upload to {SERVER}:")
    print(f"  {len(board['scenes'])} scenes, {len(body):,} bytes, showing {shown} lines of code from {len(cited)} files:")
    for p in sorted(cited):
        ranges = [f"{s['source']['start_line']}-{s['source']['end_line']}" for s in board["scenes"] if s["source"]["path"] == p]
        print(f"    {p}  (lines {', '.join(ranges)})")
    print(f"  GitHub links: {'github.com/' + repo + ' at ' + sha[:7] if repo else 'none (not pushed, or no GitHub remote)'}")
    print("  Nothing else from the repository is sent.")
    if args.dry_run or not args.yes:
        print("\nNot uploaded." + ("" if args.dry_run else " Ask the person, then run again with --yes."))
        return 0 if args.dry_run else 3
    req = urllib.request.Request(f"{SERVER}/api/import", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": f"video-learn-lesson-skill/{VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            out = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            msg = json.loads(exc.read())["error"]["message"]
        except Exception:
            msg = f"the server answered {exc.code}"
        print(f"Upload failed: {msg}")
        return 1
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"Upload failed: couldn't reach {SERVER} ({exc}).")
        return 1
    print(f"\nLesson ready: {out['url']}")
    print("Open it in your browser: the first browser to open the link becomes the lesson's owner.")
    print("It plays with captions right away; click Voice to add narration.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lesson.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--diff", nargs="?", const="", default=None, metavar="BASE")
    c = sub.add_parser("check")
    c.add_argument("file")
    p = sub.add_parser("publish")
    p.add_argument("file")
    p.add_argument("--question", default="")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--yes", action="store_true", help="the person agreed to upload")
    args = ap.parse_args(argv)
    try:
        return {"scan": cmd_scan, "check": cmd_check, "publish": cmd_publish}[args.cmd](args)
    except Problem as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
