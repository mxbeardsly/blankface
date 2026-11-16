"""Assemble narration, footage and captions into a finished video with ffmpeg."""
from __future__ import annotations

import random
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .core import ROOT, config

FPS = 30


def _run(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def _probe_duration(p: Path) -> float:
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "csv=p=0", str(p)]).decode().strip()
    return float(out or 0)


def _segment(src: Path, dur: float, w: int, h: int, out: Path) -> None:
    length = _probe_duration(src)
    start = random.uniform(0, max(length - dur - 0.5, 0)) if length > dur + 1 else 0
    zoom = random.choice(["in", "out"])
    z = "1.0+0.06*t/{d}" if zoom == "in" else "1.06-0.06*t/{d}"
    z = z.format(d=max(dur, 0.1))
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
          f"scale=w='trunc(iw*({z})/2)*2':h='trunc(ih*({z})/2)*2':eval=frame,"
          f"crop={w}:{h},setsar=1,fps={FPS},format=yuv420p")
    _run(["-ss", f"{start:.2f}", "-stream_loop", "-1", "-i", str(src), "-t", f"{dur:.3f}",
          "-an", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(out)])


def _ass_time(t: float) -> str:
    t = max(t, 0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def _captions(words: list[dict], hook: str, portrait: bool, path: Path) -> None:
    w, h = (1080, 1920) if portrait else (1920, 1080)
    size, margin = (100, 620) if portrait else (68, 90)
    hook_size = 110 if portrait else 76
    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Poppins,{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,7,3,2,60,60,{margin},1
Style: Hook,Poppins,{hook_size},&H00000000,&H00000000,&H0000E5FF,&H0000E5FF,1,0,0,0,100,100,0,0,3,24,0,8,80,80,{220 if portrait else 80},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    if hook:
        hook_wrapped = "\\N".join(textwrap.wrap(hook.upper(), 16 if portrait else 28))
        lines.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(2.6)},Hook,,0,0,0,,{{\\fad(120,200)}}{hook_wrapped}")
    # chunks of up to 3 words; break on punctuation
    chunks, cur = [], []
    for wd in words:
        cur.append(wd)
        if len(cur) == 3 or wd["word"][-1:] in ".,!?;:":
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    for ci, ch in enumerate(chunks):
        end_of_chunk = chunks[ci + 1][0]["start"] if ci + 1 < len(chunks) else ch[-1]["end"] + 0.3
        for wi, wd in enumerate(ch):
            st = wd["start"]
            en = ch[wi + 1]["start"] if wi + 1 < len(ch) else end_of_chunk
            txt = " ".join(
                ("{\\c&H0000E5FF&}" + x["word"].upper() + "{\\c&H00FFFFFF&}") if j == wi else x["word"].upper()
                for j, x in enumerate(ch))
            pop = "{\\fscx108\\fscy108\\t(0,90,\\fscx100\\fscy100)}" if wi == 0 else ""
            lines.append(f"Dialogue: 0,{_ass_time(st)},{_ass_time(en)},Cap,,0,0,0,,{pop}{txt}")
    path.write_text(hdr + "\n".join(lines) + "\n")


def build(clips: list[Path], timing: dict, audio: Path, hook: str, portrait: bool,
          workdir: Path, out: Path) -> Path:
    w, h = (1080, 1920) if portrait else (1920, 1080)
    starts = timing["beat_starts"] + [timing["duration"]]
    segs = []
    for i, src in enumerate(clips):
        dur = max(starts[i + 1] - starts[i], 0.4)
        seg = workdir / f"seg_{i:03d}.mp4"
        _segment(src, dur, w, h, seg)
        segs.append(seg)
    lst = workdir / "segments.txt"
    lst.write_text("".join(f"file '{s.resolve()}'\n" for s in segs))
    joined = workdir / "joined.mp4"
    _run(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)])

    ass = workdir / "captions.ass"
    _captions(timing["words"], hook, portrait, ass)
    fontdir = (ROOT / config()["video"]["caption_font"]).parent
    _run(["-i", str(joined), "-i", str(audio),
          "-filter_complex",
          f"[0:v]ass={ass}:fontsdir={fontdir}[v];[1:a]loudnorm=I=-14:TP=-1.5:LRA=11,apad[a]",
          "-map", "[v]", "-map", "[a]", "-t", f"{timing['duration']:.3f}",
          "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
    return out


def thumbnail(video: Path, title: str, out: Path) -> Path:
    """Landscape thumbnail: blurred frame plus big title text."""
    frame = out.with_suffix(".frame.jpg")
    _run(["-ss", "3", "-i", str(video), "-frames:v", "1", str(frame)])
    img = Image.open(frame).convert("RGB").resize((1280, 720))
    img = img.filter(ImageFilter.GaussianBlur(2))
    dark = Image.new("RGB", img.size, (0, 0, 0))
    img = Image.blend(img, dark, 0.35)
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(ROOT / config()["video"]["caption_font"]), 96)
    words = title.upper().split()[:6]
    text = "\n".join(textwrap.wrap(" ".join(words), 14))
    d.multiline_text((70, 360), text, font=font, fill=(255, 229, 0), anchor="lm",
                     stroke_width=8, stroke_fill=(0, 0, 0), spacing=10)
    img.save(out, quality=92)
    frame.unlink(missing_ok=True)
    return out
