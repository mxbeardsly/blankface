"""Post approved videos through Upload-Post (already approved by YouTube,
TikTok and Meta, so uploads go public instead of getting locked private)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import requests

from .core import OFFLINE, env, load, now

API = "https://api.upload-post.com/api"

# Posting slots in UTC. 17:00 and 01:00 UTC are 11am and 7pm US Central,
# which lands lunchtime and evening for most North American viewers.
SHORT_SLOTS = [17, 1]
LONG_SLOT = 16


def next_slot(niche_id: str, kind: str) -> dt.datetime:
    taken = {h["scheduled_for"] for h in load("history.json", [])
             if h.get("niche") == niche_id and h.get("scheduled_for")}
    t = now() + dt.timedelta(minutes=20)
    hours = SHORT_SLOTS if kind == "short" else [LONG_SLOT]
    for day in range(0, 30):
        d = (t + dt.timedelta(days=day)).date()
        for hr in sorted(hours):
            cand = dt.datetime(d.year, d.month, d.day, hr, tzinfo=dt.timezone.utc)
            if cand > t and cand.isoformat() not in taken:
                if kind == "long" and d.weekday() not in (1, 3, 5):  # Tue Thu Sat
                    continue
                return cand
    return t


def post(video: Path, meta: dict, platforms: list[str], user: str, when: dt.datetime,
         thumbnail: Path | None = None) -> dict:
    s = meta["script"]
    caption = s["title"]
    tags = [h.lstrip("#") for h in s.get("hashtags", [])][:10]
    desc = s["description"].strip() + "\n\n" + " ".join("#" + t for t in tags)
    if meta.get("credits"):
        desc += "\n\nFootage via Pexels: " + ", ".join(sorted(set(meta["credits"])))
    form = {
        "user": user,
        "external_id": meta["id"],
        "title": caption,
        "description": desc,
        "scheduled_date": when.isoformat().replace("+00:00", "Z"),
        "timezone": "UTC",
        # honest AI disclosure on every platform
        "containsSyntheticMedia": "true", "is_aigc": "true", "is_ai_generated": "true",
        "selfDeclaredMadeForKids": "false",
        "privacyStatus": "public",
        "categoryId": "27",  # Education
        "youtube_title": caption[:100],
        "tiktok_title": (caption + " " + " ".join("#" + t for t in tags[:4]))[:2200],
        "instagram_title": (caption + "\n\n" + " ".join("#" + t for t in tags[:8]))[:2200],
        "privacy_level": "PUBLIC_TO_EVERYONE",
        "post_mode": "DIRECT_POST",
        "media_type": "REELS",
        "first_comment": s.get("pinned_comment", ""),
    }
    data = [(k, v) for k, v in form.items() if v != ""]
    data += [("platform[]", p) for p in platforms]
    data += [("tags[]", t) for t in tags]
    if OFFLINE:
        return {"success": True, "job_id": "offline", "scheduled_date": form["scheduled_date"]}
    files = {"video": (video.name, open(video, "rb"), "video/mp4")}
    if thumbnail:
        files["thumbnail"] = (thumbnail.name, open(thumbnail, "rb"), "image/jpeg")
    r = requests.post(f"{API}/upload", headers={
        "Authorization": f"Apikey {env('UPLOAD_POST_API_KEY')}",
        "Idempotency-Key": f"blankface-{meta['id']}"}, data=data, files=files, timeout=900)
    if r.status_code >= 400:
        raise RuntimeError(f"Upload-Post {r.status_code}: {r.text[:400]}")
    return r.json()


def history_urls() -> list[dict]:
    """Recent upload history (used to find the public YouTube URL later)."""
    if OFFLINE:
        return []
    r = requests.get(f"{API}/uploadposts/history",
                     headers={"Authorization": f"Apikey {env('UPLOAD_POST_API_KEY')}"},
                     params={"limit": 100}, timeout=60)
    r.raise_for_status()
    j = r.json()
    return j.get("history") or j.get("data") or j.get("results") or []
