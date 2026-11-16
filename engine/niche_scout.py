"""Pick the niches. Claude proposes and scores, live YouTube data checks it."""
from __future__ import annotations

from .core import ask, config, load, now, save
from .youtube_data import outlier_scan

PROPOSE = """You are choosing niches for a faceless, AI produced short video channel.
Production is: an original narrated script (AI voice), stock footage and simple
graphics, burned in captions. No faces, no reused clips from other creators.

Propose 8 distinct niches. Each must:
- be explainable with original narration over generic stock footage
- have an obvious way to earn beyond ad revenue (affiliate programs, a cheap
  digital product, or sponsors). Name real affiliate programs where you can.
- attract adult viewers in the US, UK, Canada or Australia (higher ad value)
- support at least 200 distinct video ideas without repeating itself
- NOT fall in any of these banned areas: {banned}

Score each 1 to 5 on: viewer_value (ad and affiliate value per viewer),
monetization_paths, ai_visual_fit (can stock footage really carry it),
evergreen_depth, and originality_room (space to add a real point of view so
the channel is not "mass produced"). Also give two YouTube search queries a
viewer would type for this niche.

JSON shape:
{{"niches": [{{"name": str, "angle": str, "audience": str,
  "monetization": [str], "affiliate_programs": [str],
  "scores": {{"viewer_value": int, "monetization_paths": int,
  "ai_visual_fit": int, "evergreen_depth": int, "originality_room": int}},
  "queries": [str, str]}}]}}"""

BRAND = """Create a channel brand kit for this niche:
{niche}

JSON shape:
{{"channel_name": str, "handle_ideas": [str, str, str], "bio": str,
  "voice_style": str, "tone_rules": [str], "content_pillars": [str],
  "series_formats": [str], "cta_line": str,
  "never_say": [str]}}

Content pillars: 4 to 6 recurring themes. Series formats: 3 repeatable
formats (for example "3 myths about X", "what happens if X"). The brand needs a
real point of view so the videos read as a channel with a voice, not a feed of
templated clips."""

STUB = {"niches": [{
    "name": "Weird history of everyday objects", "angle": "the surprising origin behind ordinary things",
    "audience": "curious adults 25 to 54", "monetization": ["Amazon affiliate", "history book picks"],
    "affiliate_programs": ["Amazon Associates", "Audible"],
    "scores": {"viewer_value": 3, "monetization_paths": 3, "ai_visual_fit": 5,
               "evergreen_depth": 5, "originality_room": 4},
    "queries": ["history of everyday objects", "why does X exist"]}]}
BRAND_STUB = {"channel_name": "Origin Stories", "handle_ideas": ["@originstories"],
              "bio": "The strange backstory of ordinary things.", "voice_style": "warm, wry narrator",
              "tone_rules": ["lead with the surprise"], "content_pillars": ["kitchen", "clothing"],
              "series_formats": ["Why does X exist"], "cta_line": "Follow for one origin story a day.",
              "never_say": ["guaranteed"]}


def _score(n: dict, data: list[dict]) -> float:
    s = n["scores"]
    rubric = (2 * s["viewer_value"] + 1.5 * s["monetization_paths"] + s["ai_visual_fit"]
              + s["evergreen_depth"] + 1.5 * s["originality_room"])  # max 35
    # Market signal: are small channels still breaking through?
    small = max((d["small_channel_hits"] for d in data), default=0)  # 0 to 1
    median = max((d["median_views"] for d in data), default=0)
    demand = min(median / 500_000, 1.0)
    return round(rubric / 35 * 60 + small * 25 + demand * 15, 1)  # 0 to 100


def run(force: bool = False) -> dict:
    state = load("niches.json", {})
    if state.get("active") and not force:
        return state
    cfg = config()
    proposals = ask(PROPOSE.format(banned="; ".join(cfg["banned_niche_areas"])),
                    offline_stub=STUB)["niches"]
    for n in proposals:
        n["market"] = [outlier_scan(q) for q in n["queries"][:2]]
        n["total_score"] = _score(n, n["market"])
    proposals.sort(key=lambda n: n["total_score"], reverse=True)
    active = []
    for n in proposals[: cfg["cadence"]["active_niches"]]:
        n["brand"] = ask(BRAND.format(niche={k: n[k] for k in ("name", "angle", "audience")}),
                         offline_stub=BRAND_STUB)
        n["id"] = f"n{len(active) + 1}"
        n["voice_id"] = cfg["voice"]["default_voice_id"]
        n["started"] = now().isoformat()
        n["upload_post_user"] = f"niche{len(active) + 1}"
        active.append(n)
    state = {"chosen_at": now().isoformat(), "active": active,
             "candidates": proposals, "retired": state.get("retired", [])}
    save("niches.json", state)
    return state
