"""Read only YouTube Data API helpers (API key, no OAuth, no audit needed)."""
from __future__ import annotations

import datetime as dt
import re

import requests

from .core import OFFLINE, env

API = "https://www.googleapis.com/youtube/v3"


def _get(path: str, **params):
    params["key"] = env("YOUTUBE_API_KEY")
    r = requests.get(f"{API}/{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def outlier_scan(query: str, days: int = 90, shorts: bool = True) -> dict:
    """How well do SMALL channels do on this topic lately?

    Returns median views of recent top videos and the share of those coming
    from channels under 50K subscribers. Lots of small channel hits means the
    algorithm is still handing out views to newcomers in this niche.
    """
    if OFFLINE:
        return {"query": query, "videos": 0, "median_views": 0, "small_channel_hits": 0.0}
    after = (dt.datetime.utcnow() - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    s = _get("search", part="snippet", q=query, type="video", order="viewCount",
             publishedAfter=after, maxResults=25, relevanceLanguage="en",
             videoDuration="short" if shorts else "medium")
    ids = [i["id"]["videoId"] for i in s.get("items", [])]
    if not ids:
        return {"query": query, "videos": 0, "median_views": 0, "small_channel_hits": 0.0}
    v = _get("videos", part="statistics,snippet", id=",".join(ids))
    vids = [(int(x["statistics"].get("viewCount", 0)), x["snippet"]["channelId"])
            for x in v.get("items", [])]
    chan_ids = sorted({c for _, c in vids})
    c = _get("channels", part="statistics", id=",".join(chan_ids[:50]))
    subs = {x["id"]: int(x["statistics"].get("subscriberCount", 0) or 0)
            for x in c.get("items", [])}
    views = sorted(n for n, _ in vids)
    hits = [n for n, ch in vids if subs.get(ch, 0) < 50_000 and n >= 100_000]
    return {
        "query": query,
        "videos": len(vids),
        "median_views": views[len(views) // 2] if views else 0,
        "small_channel_hits": round(len(hits) / max(len(vids), 1), 2),
    }


def video_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"(?:shorts/|v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


def video_stats(ids: list[str]) -> dict[str, dict]:
    if OFFLINE or not ids:
        return {}
    out = {}
    for i in range(0, len(ids), 50):
        v = _get("videos", part="statistics", id=",".join(ids[i:i + 50]))
        for x in v.get("items", []):
            st = x["statistics"]
            out[x["id"]] = {k: int(st.get(k, 0)) for k in ("viewCount", "likeCount", "commentCount")}
    return out
