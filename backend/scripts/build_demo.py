"""Build the example lesson (shared/demo-lesson.json) from shared/demo-lesson.source.json.

The example teaches this repository at a fixed commit. Its scenes name code by an anchor
(a string to find) instead of by line number, and this script resolves every anchor
against `git show <sha>:<path>` and fills each code scene through the same grounding the
app uses, so the example's code is exactly what's in that commit.

    python backend/scripts/build_demo.py
"""

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import grounding  # noqa: E402
from app.github import Snapshot  # noqa: E402
from app.storyboard import Storyboard  # noqa: E402


def show(sha: str, path: str) -> str:
    return subprocess.run(["git", "show", f"{sha}:{path}"], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def line_of(text: str, needle: str, path: str) -> int:
    for n, line in enumerate(text.split("\n"), 1):
        if needle in line:
            return n
    sys.exit(f"anchor {needle!r} not found in {path}")


def main() -> None:
    spec = json.loads((ROOT / "shared" / "demo-lesson.source.json").read_text())
    sha = spec["sha"]
    files: dict[str, str] = {}
    scenes = []
    for scene in spec["storyboard"]["scenes"]:
        anchor = scene.pop("anchor", None)
        source = {"path": "", "start_line": 0, "end_line": 0}
        if anchor:
            path = anchor["path"]
            text = files.setdefault(path, show(sha, path))
            start = line_of(text, anchor["find"], path)
            end = line_of(text, anchor["end_find"], path) if "end_find" in anchor else start + anchor["lines"] - 1
            source = {"path": path, "start_line": start, "end_line": end}
        items = []
        for item in scene["items"]:
            find = item.pop("find", None)
            item["line"] = line_of(files[source["path"]], find, source["path"]) if find else 0
            items.append(item)
        scenes.append({**scene, "items": items, "code": "", "source": source})

    board = Storyboard.model_validate({**spec["storyboard"], "scenes": scenes})
    snap = Snapshot(*spec["repo"].split("/"), sha=sha, ref=sha, files=files)
    issues = grounding.problems(board, snap)
    if issues:
        sys.exit("demo lesson has bad citations:\n- " + "\n- ".join(issues))
    out = {"repo": spec["repo"], "sha": sha, "storyboard": grounding.ground(board, snap).model_dump()}
    (ROOT / "shared" / "demo-lesson.json").write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote shared/demo-lesson.json: {len(board.scenes)} scenes from {spec['repo']}@{sha[:7]}")


if __name__ == "__main__":
    main()
