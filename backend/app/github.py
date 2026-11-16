"""GitHub: read a public repository so Claude can teach from it.

The whole repository arrives in one request, as the tarball GitHub serves for any public
commit. Text files are kept (vendored code, lockfiles, binaries and huge files are
skipped) and stored compressed, keyed by commit, so a repository is downloaded once per
commit no matter how many lessons are made from it.

The GitHub REST API is used only for the repository's description and default branch.
It works without a token (60 requests an hour per server); set GITHUB_TOKEN, a
fine-grained token with read access to public repositories, to raise that to 5,000.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import re
import tarfile
import time
import zlib
from dataclasses import dataclass, field

import httpx
import regex

API = "https://api.github.com"
CODELOAD = "https://codeload.github.com"

MAX_DOWNLOAD = 60 * 1024 * 1024  # compressed tarball
MAX_FILE = 512 * 1024
MAX_TOTAL = 8 * 1024 * 1024
MAX_FILES = 2500
MAX_UNPACKED = 400 * 1024 * 1024  # everything in the archive, kept or not
MAX_MEMBERS = 200_000
MAX_CANDIDATES = 32 * 1024 * 1024  # text held while choosing what to keep
SEARCH_SECONDS = 2.0

SKIP_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", "out", ".next", ".nuxt", "target", "__pycache__",
    ".venv", "venv", "env", ".tox", ".mypy_cache", ".pytest_cache", "coverage", ".idea", ".vscode",
    "bower_components", ".gradle", "Pods", ".terraform", ".cache", "site-packages",
}
SKIP_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock", "Gemfile.lock",
    "composer.lock", "go.sum", "bun.lockb", "uv.lock", ".DS_Store",
}
SKIP_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".svgz", ".pdf", ".zip", ".gz", ".tar", ".jar",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4", ".mov", ".wav", ".ogg", ".so", ".dylib",
    ".dll", ".exe", ".bin", ".pyc", ".class", ".o", ".a", ".min.js", ".min.css", ".map", ".db",
    ".sqlite", ".parquet", ".npz", ".npy", ".pkl", ".pt", ".onnx", ".h5", ".ipynb_checkpoints",
)

URL = re.compile(
    r"^\s*(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?"
    r"(?:/(?:tree|blob)/([^\s?#]+?))?/?(?:[?#].*)?\s*$"
)
SHORT = re.compile(r"^\s*([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?\s*$")


class RepoError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass
class Snapshot:
    owner: str
    repo: str
    sha: str
    ref: str
    description: str = ""
    files: dict[str, str] = field(default_factory=dict)
    skipped: int = 0
    truncated: bool = False
    _lines: dict[str, tuple[str, ...]] = field(default_factory=dict, repr=False, compare=False)

    @property
    def name(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def key(self) -> str:
        return f"{self.owner}/{self.repo}@{self.sha}"

    def url(self, path: str = "", start: int = 0, end: int = 0) -> str:
        base = f"https://github.com/{self.owner}/{self.repo}/blob/{self.sha}/{path}"
        if start:
            base += f"#L{start}" + (f"-L{end}" if end and end != start else "")
        return base

    def pack(self) -> bytes:
        return gzip.compress(json.dumps({"files": self.files, "skipped": self.skipped, "truncated": self.truncated}).encode())

    @classmethod
    def unpack(cls, owner: str, repo: str, sha: str, ref: str, description: str, blob: bytes) -> Snapshot:
        data = json.loads(gzip.decompress(blob))
        return cls(owner, repo, sha, ref, description, data["files"], data.get("skipped", 0), data.get("truncated", False))


def parse_repo(text: str) -> tuple[str, str, str | None]:
    """'https://github.com/o/r', 'github.com/o/r/tree/main/src', or 'o/r' -> (owner, repo, ref).

    For a tree or blob link, `ref` is everything after tree/ or blob/ ("feature/login/src"):
    a branch name can contain slashes, so which part is the branch is settled by
    resolve_ref() against GitHub, not guessed here."""
    m = URL.match(text or "") or SHORT.match(text or "")
    if not m:
        raise RepoError("bad_repo_url", "That doesn't look like a GitHub repository. Paste a link like github.com/owner/repo.")
    owner, repo = m.group(1), m.group(2)
    ref = m.group(3) if m.re is URL else None
    return owner, repo, ref


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "video-learn", "X-GitHub-Api-Version": "2022-11-28"}
    if token := os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {token}"
    return h


def repo_info(owner: str, repo: str) -> dict:
    """Description and default branch. Missing or private repositories are a clear error;
    a rate limit just means going without the description."""
    try:
        r = httpx.get(f"{API}/repos/{owner}/{repo}", headers=_headers(), timeout=15.0)
    except httpx.HTTPError:
        return {}
    if r.status_code == 404:
        raise RepoError("repo_not_found", f"github.com/{owner}/{repo} doesn't exist, or it's private. Only public repositories work for now.", 404)
    if r.status_code != 200:
        return {}
    data = r.json()
    if data.get("private"):
        raise RepoError("repo_private", "That repository is private. Only public repositories work for now.", 403)
    return data


def lookup_sha(owner: str, repo: str, ref: str | None) -> str | None:
    """The commit a branch, tag or commit id points at. None means GitHub says there is no
    such ref; a GitHub that can't answer (rate limit, outage, network) raises RepoError."""
    try:
        r = httpx.get(f"{API}/repos/{owner}/{repo}/commits/{ref or 'HEAD'}",
                      headers={**_headers(), "Accept": "application/vnd.github.sha"}, timeout=10.0)
    except httpx.HTTPError as exc:
        raise RepoError("github_unavailable", "Couldn't reach GitHub just now. Try again in a minute.", 503) from exc
    text = r.text.strip()
    if r.status_code == 200 and re.fullmatch(r"[0-9a-f]{40}", text):
        return text
    if r.status_code in (404, 422):
        return None
    raise RepoError("github_unavailable", "GitHub couldn't answer just now (it may be rate limiting). Try again in a minute.", 503)


def head_sha(owner: str, repo: str, ref: str | None) -> str | None:
    """The commit, when GitHub can say; None otherwise. Only used to reuse a stored snapshot,
    so a failure just means downloading."""
    try:
        return lookup_sha(owner, repo, ref)
    except RepoError:
        return None


def resolve_ref(owner: str, repo: str, ref_path: str | None) -> str | None:
    """The branch, tag or commit at the start of a tree/blob path: the longest prefix that
    GitHub recognises ("feature/login" in "feature/login/src/app.py")."""
    if not ref_path:
        return None
    parts = ref_path.strip("/").split("/")
    if len(parts) == 1:
        return parts[0]
    for k in range(len(parts), 0, -1):
        candidate = "/".join(parts[:k])
        # lookup_sha raises when GitHub can't answer, so an outage isn't reported as a
        # missing branch
        if lookup_sha(owner, repo, candidate):
            return candidate
    raise RepoError("ref_not_found", f"Couldn't find a branch at the start of {ref_path!r} in github.com/{owner}/{repo}. "
                    "Paste the repository's main link instead.", 404)


def keep(path: str, size: int) -> bool:
    parts = path.split("/")
    if any(p in SKIP_DIRS for p in parts[:-1]):
        return False
    name = parts[-1]
    if name in SKIP_FILES or name.lower().endswith(SKIP_SUFFIXES):
        return False
    return 0 < size <= MAX_FILE


TRANSLATION = re.compile(r"(^|/)docs?/(?!en/)[a-z]{2}(-[a-z]+)?/")
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "testing", "e2e"}


def rank(path: str) -> tuple[int, int, str]:
    """Lower sorts first: source code, then docs and tests, then translated docs."""
    low = path.lower()
    score = 0
    if TRANSLATION.search(low):
        score += 4
    if low.startswith(("docs/", "doc/", "examples/", "docs_src/")) or "/docs/" in low:
        score += 2
    if any(part in TEST_DIRS for part in low.split("/")[:-1]):
        score += 1
    if low.endswith((".md", ".rst", ".txt")) and "/" in low:
        score += 1
    return (score, path.count("/"), path)


def download(owner: str, repo: str, ref: str | None = None) -> Snapshot:
    info = repo_info(owner, repo)
    owner, repo = (info.get("full_name") or f"{owner}/{repo}").split("/", 1)
    ref = resolve_ref(owner, repo, ref) or info.get("default_branch") or "HEAD"

    try:
        with httpx.stream("GET", f"{CODELOAD}/{owner}/{repo}/tar.gz/{ref}", headers={"User-Agent": "video-learn"},
                          timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=True) as r:
            if r.status_code == 404:
                raise RepoError("repo_not_found", f"Couldn't find {ref!r} in github.com/{owner}/{repo}. Is the repository public?", 404)
            if r.status_code != 200:
                raise RepoError("repo_download_failed", f"GitHub didn't send the repository ({r.status_code}). Try again in a moment.", 502)
            buf = io.BytesIO()
            for chunk in r.iter_bytes():
                buf.write(chunk)
                if buf.tell() > MAX_DOWNLOAD:
                    raise RepoError("repo_too_big", "That repository is too big to read (over 60 MB compressed). Try a smaller one.", 413)
    except httpx.TimeoutException as exc:
        raise RepoError("repo_timeout", "GitHub took too long to send the repository. Try again.", 504) from exc
    except httpx.HTTPError as exc:
        raise RepoError("repo_unreachable", "The server couldn't reach GitHub. Try again in a moment.", 502) from exc

    buf.seek(0)
    snap = Snapshot(owner=owner, repo=repo, sha="", ref=ref, description=(info.get("description") or "").strip())
    candidates: list[tuple[tuple[int, int, str], str]] = []
    held = unpacked = members = 0
    try:
        # One pass in archive order ("r|gz" never rewinds the stream).
        with tarfile.open(fileobj=buf, mode="r|gz") as tar:
            for member in tar:
                members += 1
                unpacked += max(0, member.size)
                if members > MAX_MEMBERS or unpacked > MAX_UNPACKED:
                    raise RepoError("repo_too_big", "That repository is too big to read. Try a smaller one.", 413)
                if not snap.sha:
                    # GitHub puts the full commit id in the archive's pax header
                    snap.sha = (tar.pax_headers or {}).get("comment", "")
                if not member.isfile():
                    continue
                path = member.name.split("/", 1)[1] if "/" in member.name else member.name
                if not keep(path, member.size):
                    snap.skipped += 1
                    continue
                if held + member.size > MAX_CANDIDATES:
                    # Full: make room by dropping the worst-ranked files held so far, unless
                    # this one ranks worse than all of them.
                    candidates.sort(key=lambda c: c[0])
                    while candidates and held + member.size > MAX_CANDIDATES and candidates[-1][0] > rank(path):
                        held -= len(candidates.pop()[1].encode())
                        snap.skipped += 1
                    snap.truncated = True
                    if held + member.size > MAX_CANDIDATES:
                        snap.skipped += 1
                        continue
                raw = tar.extractfile(member).read()  # type: ignore[union-attr]
                if b"\x00" in raw[:4096]:
                    snap.skipped += 1
                    continue
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    snap.skipped += 1
                    continue
                candidates.append((rank(path), text.replace("\r\n", "\n")))
                held += len(raw)
    except (tarfile.TarError, EOFError, OSError, zlib.error) as exc:
        raise RepoError("repo_unreadable", "GitHub sent an archive that couldn't be read. Try again.", 502) from exc

    # When the repository is bigger than the budget, keep the code that explains it first.
    total = 0
    for key, text in sorted(candidates, key=lambda c: c[0]):
        size = len(text.encode())
        if len(snap.files) >= MAX_FILES or total + size > MAX_TOTAL:
            snap.truncated = True
            snap.skipped += 1
            continue
        snap.files[key[2]] = text
        total += size
    snap.files = dict(sorted(snap.files.items()))

    if not snap.sha:
        snap.sha = ref
    if not snap.files:
        raise RepoError("repo_empty", "That repository has no source files to read.", 422)
    return snap


# ---------------------------------------------------------------- reading a snapshot


def lines(snap: Snapshot, path: str) -> tuple[str, ...]:
    """A file's lines, cached on the snapshot (so the cache goes when the snapshot does)."""
    if path not in snap._lines:
        text = snap.files[path]
        # a final newline ends the last line; it doesn't start an empty one
        snap._lines[path] = tuple((text[:-1] if text.endswith("\n") else text).split("\n"))
    return snap._lines[path]


def tree(snap: Snapshot, prefix: str = "", limit: int = 400) -> str:
    """A folder listing: subfolders with file counts, then files with line counts."""
    prefix = prefix.strip("/")
    pre = f"{prefix}/" if prefix else ""
    dirs: dict[str, int] = {}
    files: list[str] = []
    for path in sorted(snap.files):
        if not path.startswith(pre):
            continue
        rest = path[len(pre):]
        if "/" in rest:
            d = rest.split("/", 1)[0]
            dirs[d] = dirs.get(d, 0) + 1
        else:
            files.append(f"{pre}{rest}  ({len(lines(snap, path))} lines)")
    if not dirs and not files:
        return f"No folder called {prefix!r}."
    out = [f"{pre}{d}/  ({n} files)" for d, n in sorted(dirs.items())] + files
    if len(out) > limit:
        out = out[:limit] + [f"... and {len(out) - limit} more"]
    return "\n".join(out)


def read(snap: Snapshot, path: str, start: int = 1, end: int = 0, max_lines: int = 300) -> str:
    path = path.strip().lstrip("/")
    if path not in snap.files:
        close = [p for p in snap.files if p.endswith("/" + path) or p.split("/")[-1] == path.split("/")[-1]][:5]
        hint = f" Did you mean {', '.join(close)}?" if close else ""
        raise ValueError(f"No file called {path!r}.{hint}")
    ls = lines(snap, path)
    start = max(1, start or 1)
    end = min(len(ls), end or len(ls), start + max_lines - 1)
    body = "\n".join(f"{n:>5}  {ls[n - 1]}" for n in range(start, end + 1))
    more = f"\n[{len(ls) - end} more lines; read again from line {end + 1}]" if end < len(ls) else ""
    return f"{path} lines {start}-{end} of {len(ls)}\n{body}{more}"


def search(snap: Snapshot, pattern: str, prefix: str = "", limit: int = 60) -> str:
    """Case-insensitive search: a regular expression if it compiles, else plain text. The
    `regex` module runs with a time limit and without holding the interpreter lock, so a
    pathological pattern can't freeze the server."""
    pattern = pattern[:200]
    try:
        rx = regex.compile(pattern, regex.I)
    except regex.error:
        rx = regex.compile(regex.escape(pattern), regex.I)
    prefix = prefix.strip("/")
    deadline = time.monotonic() + SEARCH_SECONDS
    hits = []
    for path in sorted(snap.files):
        if prefix and not path.startswith(prefix):
            continue
        for n, line in enumerate(lines(snap, path), 1):
            left = deadline - time.monotonic()
            try:
                if left <= 0:
                    raise TimeoutError
                found = rx.search(line, timeout=left, concurrent=True)
            except TimeoutError:
                more = "\n".join(hits)
                return (more + "\n" if more else "") + "[search stopped: the pattern took too long; use a simpler one]"
            if found:
                hits.append(f"{path}:{n}: {line.strip()[:160]}")
                if len(hits) >= limit:
                    return "\n".join(hits) + f"\n[stopped at {limit} matches; narrow the search]"
    return "\n".join(hits) or f"No matches for {pattern!r}."


def readme(snap: Snapshot, max_lines: int = 120) -> str:
    for name in ("README.md", "readme.md", "README.rst", "README.txt", "README"):
        if name in snap.files:
            return "\n".join(lines(snap, name)[:max_lines])
    return ""
