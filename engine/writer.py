"""Ideas, scripts, and a separate fact and policy check."""
from __future__ import annotations

import json

from .core import ask, load, save

IDEAS = """You run the faceless channel "{channel}" ({angle}) for {audience}.
Content pillars: {pillars}. Series formats: {formats}.

Generate {n} new video ideas. Each must be specific, surprising, and true
(no myths presented as fact). Mix pillars and formats.

What has worked best so far (higher views first):
{winners}
What flopped (avoid these angles):
{losers}
Already used (do not repeat or near repeat):
{used}

JSON: {{"ideas": [{{"topic": str, "format": str, "why_it_hooks": str}}]}}"""

SCRIPT = """Write a {kind} script for the channel "{channel}".
Voice: {voice}. Tone rules: {tone}. Never say: {never}.
Topic: {topic} (format: {fmt}).

Rules:
- About {words} spoken words total. Every sentence earns its place.
- The first sentence is the hook: a surprising claim or question, under 12
  words, no greetings, no "in this video".
- Original commentary and a clear point of view: explain WHY it matters or
  what most people get wrong. This channel is not a reading of facts.
- Only state facts you are confident are true. Put every checkable factual
  claim in "claims". No invented statistics, quotes, or studies.
- Split into beats of 1 to 2 sentences. For each beat give a concrete stock
  footage search query (2 to 4 plain words a stock site would match, like
  "old factory workers" not "the concept of progress").
- End with this call to action, worded naturally: {cta}
{affiliate}
JSON: {{"title": str (under 70 chars, curiosity, no clickbait lies),
  "hook_text": str (max 6 words, shown on screen in the first seconds),
  "beats": [{{"narration": str, "visual": str}}],
  "description": str (2 to 3 sentences),
  "hashtags": [str],
  "pinned_comment": str,
  "claims": [str]}}"""

CHECK = """You are a strict fact checker and YouTube policy reviewer.
Review this script for a faceless educational channel.

{script}

Flag: any claim that is false, disputed, or likely invented; any invented
statistic, quote, or study; anything that would violate YouTube policy
(harmful advice, harassment, sexual content, dangerous acts, medical or
financial advice); misleading title relative to content.

JSON: {{"verdict": "pass" | "fix" | "reject",
  "problems": [{{"text": str, "issue": str, "fix": str}}]}}"""

REWRITE = """Revise this script to fix every listed problem. Remove a claim
rather than guess. Keep the same JSON shape and roughly the same length.

Script: {script}
Problems: {problems}"""


def _stub_script(topic: str) -> dict:
    return {
        "title": f"The weird reason {topic} exists",
        "hook_text": "This was an accident",
        "beats": [
            {"narration": "This everyday object started as a mistake.", "visual": "factory workers vintage"},
            {"narration": "A worker noticed something nobody else did.", "visual": "workshop tools"},
            {"narration": "Within ten years it was in every home.", "visual": "family kitchen"},
            {"narration": "Follow for one origin story a day.", "visual": "city street night"},
        ],
        "description": "The odd backstory of an ordinary thing.",
        "hashtags": ["#history", "#didyouknow"],
        "pinned_comment": "What object should we cover next?",
        "claims": [],
    }


def next_idea(niche: dict, history: list[dict], stats: dict) -> dict:
    bank = load("ideas.json", {})
    queue = bank.get(niche["id"], [])
    if len(queue) < 3:
        b = niche["brand"]
        mine = [h for h in history if h["niche"] == niche["id"]]
        scored = sorted(
            ((stats.get(h.get("youtube_id") or "", {}).get("viewCount", -1), h["title"]) for h in mine),
            reverse=True)
        scored = [s for s in scored if s[0] >= 0]
        fresh = ask(IDEAS.format(
            channel=b["channel_name"], angle=niche["angle"], audience=niche["audience"],
            pillars=", ".join(b["content_pillars"]), formats=", ".join(b["series_formats"]),
            n=20,
            winners="\n".join(f"{v} views: {t}" for v, t in scored[:8]) or "none yet",
            losers="\n".join(
                [f"{v} views: {t}" for v, t in (scored[-5:] if len(scored) > 10 else [])]
                + [f"owner rejected: {h['title']} ({h.get('reason') or 'no reason'})"
                   for h in mine if h.get("status") == "rejected"][-10:]) or "none yet",
            used="\n".join(h["topic"] for h in mine[-120:]) or "none",
        ), offline_stub={"ideas": [{"topic": "the paperclip", "format": "Why does X exist",
                                    "why_it_hooks": "everyone owns one"}] * 3})["ideas"]
        queue.extend(fresh)
    idea = queue.pop(0)
    bank[niche["id"]] = queue
    save("ideas.json", bank)
    return idea


def write(niche: dict, idea: dict, kind: str, target_seconds: int) -> tuple[dict, list]:
    """Returns (script, unresolved_problems). Raises ValueError if rejected."""
    b = niche["brand"]
    words = int(target_seconds * 2.5)  # about 150 spoken words per minute
    links = load("affiliates.json", {}).get(niche["id"], [])
    affiliate = ("- If it fits naturally, the description may mention: "
                 + "; ".join(f"{l['name']} ({l['url']})" for l in links)) if links else ""
    script = ask(SCRIPT.format(
        kind="vertical Short" if kind == "short" else "6 minute horizontal YouTube",
        channel=b["channel_name"], voice=b["voice_style"], tone="; ".join(b["tone_rules"]),
        never=", ".join(b["never_say"]), topic=idea["topic"], fmt=idea["format"],
        words=words, cta=b["cta_line"], affiliate=affiliate,
    ), max_tokens=6000, offline_stub=_stub_script(idea["topic"]))

    review = ask(CHECK.format(script=json.dumps(script)), model_role="checker",
                 offline_stub={"verdict": "pass", "problems": []})
    if review["verdict"] == "reject":
        raise ValueError("checker rejected: " + "; ".join(p["issue"] for p in review["problems"]))
    if review["verdict"] == "fix" and review["problems"]:
        script = ask(REWRITE.format(script=json.dumps(script), problems=json.dumps(review["problems"])),
                     max_tokens=6000, offline_stub=script)
        second = ask(CHECK.format(script=json.dumps(script)), model_role="checker",
                     offline_stub={"verdict": "pass", "problems": []})
        if second["verdict"] == "reject":
            raise ValueError("checker rejected after rewrite")
        return script, second["problems"]
    return script, []
