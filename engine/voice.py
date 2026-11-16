"""Narration audio plus word level timings (for captions and cut points)."""
from __future__ import annotations

import base64
import re
import subprocess
from pathlib import Path

import requests

from .core import OFFLINE, add_spend, config, env


def _words_from_alignment(text: str, starts: list[float], ends: list[float]) -> list[dict]:
    words, i = [], 0
    for m in re.finditer(r"\S+", text):
        a, b = m.start(), m.end() - 1
        if b >= len(starts):
            break
        words.append({"word": m.group(), "start": starts[a], "end": ends[b], "char": a})
        i += 1
    return words


def synthesize(beats: list[dict], voice_id: str, out_mp3: Path) -> dict:
    """Returns {"duration", "words": [...], "beat_starts": [...]}."""
    text = ""
    beat_chars = []
    for b in beats:
        beat_chars.append(len(text))
        text += b["narration"].strip() + " "
    text = text.strip()

    if OFFLINE:
        words, t = [], 0.3
        for m in re.finditer(r"\S+", text):
            d = 0.12 + 0.045 * len(m.group())
            words.append({"word": m.group(), "start": t, "end": t + d, "char": m.start()})
            t += d + 0.06
        duration = t + 0.5
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "anullsrc=r=44100:cl=mono", "-t", f"{duration:.2f}", "-q:a", "9",
                        str(out_mp3)], check=True)
    else:
        cfg = config()["voice"]
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps",
            headers={"xi-api-key": env("ELEVENLABS_API_KEY"), "Content-Type": "application/json"},
            json={"text": text, "model_id": cfg["model_id"],
                  "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.2}},
            timeout=300,
        )
        r.raise_for_status()
        j = r.json()
        out_mp3.write_bytes(base64.b64decode(j["audio_base64"]))
        add_spend("elevenlabs_chars", len(text))
        al = j["alignment"]
        words = _words_from_alignment(text, al["character_start_times_seconds"],
                                      al["character_end_times_seconds"])
        duration = float(subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
             str(out_mp3)]).decode().strip())

    # first word at or after each beat's char offset marks the cut point
    beat_starts = []
    for c in beat_chars:
        w = next((w for w in words if w["char"] >= c), None)
        beat_starts.append(0.0 if not beat_starts else (w["start"] if w else duration))
    return {"duration": duration, "words": words, "beat_starts": beat_starts}
