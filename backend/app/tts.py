"""ElevenLabs: narration to speech, with the time each word is said.

Uses the text-to-speech `with-timestamps` endpoint, which returns the MP3 and, for every
character of the text, when it starts and ends. Those timings are what keep captions and
reveals on the right word in the player.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

API = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps"
DEFAULT_VOICE = "nPczCjzI2devNBz1zQrb"  # "Brian", a clear American narrator from ElevenLabs' default voices
DEFAULT_MODEL = "eleven_multilingual_v2"


class VoiceError(Exception):
    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass
class Spoken:
    audio: bytes
    words: list[dict[str, Any]]
    duration: float
    ms: int


def voice_id() -> str:
    return os.environ.get("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE


def model_id() -> str:
    return os.environ.get("ELEVENLABS_MODEL") or DEFAULT_MODEL


def clip_hash(voice: str, model: str, text: str) -> str:
    """Same voice, model and words = same audio, so it's only ever paid for once."""
    return hashlib.sha256(f"{voice}|{model}|{text}".encode()).hexdigest()[:32]


def words_from_alignment(text: str, alignment: dict[str, Any]) -> list[dict[str, Any]]:
    """Group per-character timings into words, with each word's place in the text."""
    chars: list[str] = alignment.get("characters") or []
    starts: list[float] = alignment.get("character_start_times_seconds") or []
    ends: list[float] = alignment.get("character_end_times_seconds") or []
    if not chars or len(chars) != len(starts) or len(chars) != len(ends):
        return []

    spoken = "".join(chars)
    words = []
    if spoken == text:
        for m in re.finditer(r"\S+", text):
            a, b = m.start(), m.end() - 1
            words.append({"text": m.group(), "start_char": m.start(), "end_char": m.end(), "start": round(starts[a], 3), "end": round(ends[b], 3)})
        return words

    # The service changed the text slightly (it can normalize whitespace). Match words in order.
    tokens = list(re.finditer(r"\S+", text))
    spoken_words = [(m.start(), m.end() - 1) for m in re.finditer(r"\S+", spoken)]
    for k, m in enumerate(tokens):
        if k < len(spoken_words):
            a, b = spoken_words[k]
            start, end = starts[a], ends[b]
        else:
            start = end = ends[-1]
        words.append({"text": m.group(), "start_char": m.start(), "end_char": m.end(), "start": round(start, 3), "end": round(end, 3)})
    return words


def speak(text: str, voice: str, model: str, previous_text: str = "", next_text: str = "") -> Spoken:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise VoiceError("voice_not_configured", "Voices aren't set up on this server yet, so the lesson plays silently with captions.", 503)

    body: dict[str, Any] = {
        "text": text,
        "model_id": model,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.78, "style": 0.0, "use_speaker_boost": True},
    }
    # Neighbouring narration keeps the intonation natural across scene boundaries.
    if previous_text:
        body["previous_text"] = previous_text[-300:]
    if next_text:
        body["next_text"] = next_text[:300]

    started = time.monotonic()
    try:
        r = httpx.post(
            API.format(voice=voice),
            params={"output_format": "mp3_44100_128"},
            headers={"xi-api-key": key, "Content-Type": "application/json"},
            json=body,
            timeout=httpx.Timeout(90.0, connect=10.0),
        )
    except httpx.TimeoutException as exc:
        raise VoiceError("voice_timeout", "The voice service took too long. Try this scene again.", 504) from exc
    except httpx.HTTPError as exc:
        raise VoiceError("voice_unreachable", "The server couldn't reach the voice service. Try again in a moment.", 502) from exc

    if r.status_code != 200:
        raise _voice_error(r)
    try:
        data = r.json()
        audio = base64.b64decode(data["audio_base64"])
        alignment = data.get("alignment") or {}
    except (ValueError, KeyError) as exc:
        raise VoiceError("voice_bad_output", "The voice service sent back something unusable. Try again.", 502) from exc

    words = words_from_alignment(text, alignment)
    ends = alignment.get("character_end_times_seconds") or []
    duration = float(ends[-1]) if ends else (words[-1]["end"] if words else 0.0)
    return Spoken(audio=audio, words=words, duration=round(duration, 3), ms=int((time.monotonic() - started) * 1000))


def _voice_error(r: httpx.Response) -> VoiceError:
    detail: Any = None
    try:
        detail = r.json().get("detail")
    except ValueError:
        pass
    status = (detail or {}).get("status", "") if isinstance(detail, dict) else ""
    if status == "quota_exceeded":
        return VoiceError("voice_quota", "The voice service is out of credits for now, so this scene can't be voiced. It still plays with captions.", 503)
    if r.status_code == 401:
        return VoiceError("voice_key_invalid", "The server's voice key was refused, so scenes can't be voiced right now.", 503)
    if r.status_code == 429:
        return VoiceError("voice_busy", "The voice service is busy. Wait a moment and try again.", 429)
    if r.status_code == 422:
        return VoiceError("voice_rejected", "The voice service couldn't read this narration. Try rewording it.", 422)
    return VoiceError("voice_down", f"The voice service had a problem ({r.status_code}). Try again in a minute.", 502)
