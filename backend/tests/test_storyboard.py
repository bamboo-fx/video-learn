import json
import pathlib
import subprocess
import sys

import pytest
from pydantic import ValidationError

from app.storyboard import Storyboard, next_scene_id, normalize, sentences, strict_json_schema

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXAMPLE = json.loads((ROOT / "shared" / "example-storyboard.json").read_text())


def test_example_storyboard_validates():
    board = Storyboard.model_validate(EXAMPLE)
    assert len(board.scenes) == 7
    assert board.scenes[0].layout == "title"


def test_example_reveals_fall_inside_their_narration():
    board = Storyboard.model_validate(EXAMPLE)
    for scene in board.scenes:
        n = len(sentences(scene.narration))
        assert all(item.at < n for item in scene.items), scene.id


def test_unknown_fields_and_layouts_are_rejected():
    bad = json.loads(json.dumps(EXAMPLE))
    bad["scenes"][0]["layout"] = "hologram"
    with pytest.raises(ValidationError):
        Storyboard.model_validate(bad)
    bad = json.loads(json.dumps(EXAMPLE))
    bad["scenes"][0]["colour"] = "red"
    with pytest.raises(ValidationError):
        Storyboard.model_validate(bad)


def test_sentences_splits_on_end_punctuation():
    text = "First one. Second one? Third! And a tail without a stop"
    spans = [text[a:b] for a, b in sentences(text)]
    assert spans == ["First one.", "Second one?", "Third!", "And a tail without a stop"]


def test_sentences_keep_dots_inside_words():
    text = "Node.js runs JavaScript. Pi is about 3.14, roughly! Done"
    spans = [text[a:b] for a, b in sentences(text)]
    assert spans == ["Node.js runs JavaScript.", "Pi is about 3.14, roughly!", "Done"]


def test_normalize_repairs_ids_and_reveals():
    raw = json.loads(json.dumps(EXAMPLE))
    raw["scenes"][1]["id"] = "s1"  # duplicate
    raw["scenes"][2]["items"][0]["at"] = 40  # past the last sentence
    raw["scenes"][0]["items"] = [{"text": "x", "detail": "", "at": 0}]  # items on a title card
    board = normalize(Storyboard.model_validate(raw))
    ids = [s.id for s in board.scenes]
    assert len(set(ids)) == len(ids)
    assert board.scenes[2].items[0].at == len(sentences(board.scenes[2].narration)) - 1
    assert board.scenes[0].items == []
    assert next_scene_id(board) == "s9"


def test_strict_schema_is_closed_and_inlined():
    schema = strict_json_schema(Storyboard)
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text

    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for v in node.values():
                check(v)
        elif isinstance(node, list):
            for v in node:
                check(v)

    check(schema)


def test_exported_schema_file_is_current():
    r = subprocess.run([sys.executable, str(ROOT / "backend/scripts/export_schema.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr or r.stdout
