"""Voice the example lesson once and ship the audio with the web app.

Writes web/public/demo-audio/<hash>.mp3 for each scene and shared/demo-voices.json with
the word timings, so /demo plays with a real voice and costs nothing per visit. Scenes
whose narration hasn't changed are skipped. This spends ElevenLabs credits (about one per
character of new narration); it prints the count before it starts.

    ELEVENLABS_API_KEY=... python backend/scripts/voice_demo.py
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import tts  # noqa: E402

AUDIO = ROOT / "web" / "public" / "demo-audio"
VOICES = ROOT / "shared" / "demo-voices.json"


def main() -> None:
    scenes = json.loads((ROOT / "shared" / "demo-lesson.json").read_text())["storyboard"]["scenes"]
    voices = json.loads(VOICES.read_text()) if VOICES.exists() else {}
    voice, model = tts.voice_id(), tts.model_id()
    todo = [s for s in scenes if voices.get(s["id"], {}).get("text") != s["narration"]]
    print(f"{len(todo)} of {len(scenes)} scenes to voice, {sum(len(s['narration']) for s in todo)} characters")
    AUDIO.mkdir(parents=True, exist_ok=True)
    for i, scene in enumerate(scenes):
        if scene not in todo:
            continue
        prev_text = scenes[i - 1]["narration"] if i else ""
        next_text = scenes[i + 1]["narration"] if i + 1 < len(scenes) else ""
        spoken = tts.speak(scene["narration"], voice, model, prev_text, next_text)
        h = tts.clip_hash(voice, model, scene["narration"])
        (AUDIO / f"{h}.mp3").write_bytes(spoken.audio)
        voices[scene["id"]] = {"hash": h, "text": scene["narration"], "url": f"/demo-audio/{h}.mp3", "duration": spoken.duration, "words": spoken.words}
        VOICES.write_text(json.dumps(voices, indent=1) + "\n")  # saved now, so a later failure can't make a rerun pay again
        print(f"{scene['id']}  {spoken.duration:5.1f}s  {len(spoken.audio) // 1024} KB")
    # drop audio no scene uses any more
    keep = {v["hash"] for k, v in voices.items() if any(s["id"] == k for s in scenes)}
    voices = {k: v for k, v in voices.items() if v["hash"] in keep}
    for f in AUDIO.glob("*.mp3"):
        if f.stem not in keep:
            f.unlink()
    VOICES.write_text(json.dumps(voices, indent=1) + "\n")


if __name__ == "__main__":
    main()
