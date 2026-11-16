"""Keep a lesson honest about the repository it teaches.

Claude cites a file and a line range for each scene; it never types the code itself. This
module checks every citation against the downloaded repository and fills each code scene
with the real lines, so the code on screen is always exactly what is in the repo.
"""

from __future__ import annotations

from app.github import Snapshot, lines
from app.storyboard import Scene, Source, Storyboard, normalize

MAX_CODE_LINES = 14


def problems(board: Storyboard, snap: Snapshot) -> list[str]:
    """What's wrong with the citations, in sentences Claude can act on. Empty = all good."""
    out = []
    for i, scene in enumerate(board.scenes, 1):
        src = scene.source
        where = f"Scene {i} ({scene.id})"
        if not src.path:
            if scene.layout == "code":
                out.append(f"{where} is a code scene with no source. Set source to a file and line range.")
            continue
        if src.path not in snap.files:
            out.append(f"{where} cites {src.path!r}, which isn't a file in the repository.")
            continue
        n = len(lines(snap, src.path))
        if not (1 <= src.start_line <= src.end_line <= n):
            out.append(f"{where} cites lines {src.start_line}-{src.end_line} of {src.path}, which has {n} lines.")
            continue
        if scene.layout == "code" and src.end_line - src.start_line + 1 > MAX_CODE_LINES:
            out.append(f"{where} shows {src.end_line - src.start_line + 1} lines; a code scene shows at most {MAX_CODE_LINES}. Pick the lines that matter.")
        for k, item in enumerate(scene.items, 1):
            if scene.layout == "code" and item.line and not (src.start_line <= item.line <= src.end_line):
                out.append(f"{where}, item {k} points at line {item.line}, outside lines {src.start_line}-{src.end_line}.")
    return out


def ground(board: Storyboard, snap: Snapshot, hand: bool = False) -> Storyboard:
    """Fill code scenes from the file and drop any citation that doesn't hold. A code scene
    that can't be grounded becomes a points scene, so no invented code is ever shown.

    `hand=True` is for a person's own edits, which are saved mid-typing: a citation that
    doesn't hold yet (a half-typed path, an empty line field) is kept as typed with no code,
    instead of turning the scene into something else under their cursor."""
    board = normalize(board)
    scenes: list[Scene] = []
    for scene in board.scenes:
        scene = scene.model_copy(deep=True)
        src = scene.source
        ok = bool(src.path) and src.path in snap.files and 1 <= src.start_line <= src.end_line <= len(lines(snap, src.path))
        if not ok and hand:
            scene.code = ""  # never typed code, but leave their citation and layout alone
        elif not ok:
            scene.source = Source(path="", start_line=0, end_line=0)
            if scene.layout == "code":
                scene.layout = "points"
                scene.code = ""
                for item in scene.items:
                    item.line = 0
        elif scene.layout == "code":
            end = min(src.end_line, src.start_line + MAX_CODE_LINES - 1)
            scene.source = Source(path=src.path, start_line=src.start_line, end_line=end)
            scene.code = "\n".join(lines(snap, src.path)[src.start_line - 1 : end])
            for item in scene.items:
                if item.line and not (src.start_line <= item.line <= end):
                    item.line = 0
        scenes.append(scene)
    return Storyboard(title=board.title, summary=board.summary, scenes=scenes)
