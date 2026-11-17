"""The three jobs the scheduler runs: produce, publish, report."""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import traceback

from . import github as gh
from . import niche_scout, publisher, render, visuals, voice, writer
from .core import OUT, add_spend, config, load, month_key, now, over_budget, save, slug
from .youtube_data import video_id_from_url, video_stats

APPROVE = re.compile(r"^\s*(yes|y|approve|approved|ok|okay|ship it|post|👍|✅)\b", re.I)
REJECT = re.compile(r"^\s*(no|n|reject|nope|skip|👎|❌)\b", re.I)


# ------------------------------------------------------------- produce


def _make_one(niche: dict, kind: str) -> dict:
    cfg = config()
    history = load("history.json", [])
    stats = load("stats.json", {}).get("videos", {})
    portrait = kind == "short"
    target = (cfg["video"]["shorts_target_seconds"] if portrait
              else cfg["video"]["longform_target_minutes"] * 60)

    for attempt in range(3):
        idea = writer.next_idea(niche, history, stats)
        try:
            script, notes = writer.write(niche, idea, kind, target)
            break
        except ValueError as e:
            history.append({"niche": niche["id"], "topic": idea["topic"], "title": idea["topic"],
                            "status": "checker_rejected", "reason": str(e), "at": now().isoformat()})
            save("history.json", history)
    else:
        raise RuntimeError("three ideas in a row failed the fact check")

    vid_id = f"{now():%Y%m%d%H%M}-{niche['id']}-{slug(script['title'], 30)}"
    work = OUT / vid_id
    work.mkdir(parents=True, exist_ok=True)
    timing = voice.synthesize(script["beats"], niche.get("voice_id") or cfg["voice"]["default_voice_id"],
                              work / "voice.mp3")
    starts = timing["beat_starts"] + [timing["duration"]]
    avoid, clips, credits, used = visuals.recently_used(), [], [], []
    for i, beat in enumerate(script["beats"]):
        c = visuals.fetch(beat["visual"], portrait, starts[i + 1] - starts[i], avoid)
        avoid.add(c["clip_id"])
        used.append(c["clip_id"])
        clips.append(c["path"])
        if c["credit"]:
            credits.append(c["credit"])
    final = render.build(clips, timing, work / "voice.mp3", script.get("hook_text", "") if portrait else "",
                         portrait, work, work / f"{vid_id}.mp4")
    thumb = None if portrait else render.thumbnail(work / "joined.mp4", script["title"], work / f"{vid_id}.jpg")
    visuals.remember(used)

    meta = {"id": vid_id, "niche": niche["id"], "kind": kind, "topic": idea["topic"],
            "script": script, "check_notes": notes, "credits": credits,
            "duration": round(timing["duration"], 1), "created": now().isoformat()}
    asset = gh.upload_asset(final)
    meta["asset_id"], meta["asset_url"] = asset["id"], asset["browser_download_url"]
    if thumb:
        t = gh.upload_asset(thumb)
        meta["thumb_asset_id"] = t["id"]

    brand = niche["brand"]["channel_name"]
    narration = "\n".join(f"> {b['narration']}" for b in script["beats"])
    flags = ("\n\n**Fact check notes (worth a glance):**\n" +
             "\n".join(f"- {p['text']}: {p['issue']}" for p in notes)) if notes else ""
    body = f"""### ▶️ [Watch the video]({meta['asset_url']})
**{brand}** · {'Short' if portrait else 'Long video'} · {meta['duration']}s

**Reply `yes` to post it, or `no` to toss it.** (Add a reason after `no` and the bot learns from it.)
Ignored videos expire after {config()['review']['expire_after_days']} days and never post.

**Title:** {script['title']}
**Hook:** {script.get('hook_text', '')}

<details><summary>Script</summary>

{narration}
</details>{flags}
"""
    meta["issue"] = gh.create_issue(f"[{brand}] {script['title']}", body, ["review"])
    queue = load("queue.json", {})
    queue[vid_id] = meta
    save("queue.json", queue)
    for seg in work.glob("seg_*.mp4"):
        seg.unlink()
    return meta


def produce(kind: str = "short") -> list[dict]:
    gh.ensure_labels()
    state = niche_scout.run()
    made, errors = [], []
    niches = state["active"]
    if kind == "long":
        week = now().isocalendar().week
        niches = [niches[week % len(niches)]] if niches else []
        if config()["cadence"]["longform_per_week"] == 0:
            return []
    per = config()["cadence"]["shorts_per_day_per_niche"] if kind == "short" else 1
    for n in niches:
        for _ in range(per * n.get("weight", 1)):
            reason = over_budget()
            if reason:
                _alert(f"Paused production: {reason}", "Raise the cap in config.yaml or wait for next month.")
                return made
            try:
                made.append(_make_one(n, kind))
            except Exception as e:  # keep going with the other niche
                errors.append(f"{n['id']}: {e}")
                traceback.print_exc()
    if errors:
        _alert("Some videos failed to build", "\n".join(f"- {e}" for e in errors))
    return made


# ------------------------------------------------------------- publish


def _decision(meta: dict) -> tuple[str | None, str]:
    iss = gh.issue(meta["issue"])
    labels = {l["name"] for l in iss.get("labels", [])}
    if "approved" in labels:
        return "approve", ""
    if "rejected" in labels:
        return "reject", ""
    for c in reversed(gh.comments(meta["issue"])):
        if c["user"]["login"].lower() != gh.owner().lower():
            continue  # only the repo owner can approve
        if APPROVE.match(c["body"]):
            return "approve", c["body"]
        if REJECT.match(c["body"]):
            return "reject", REJECT.sub("", c["body"]).strip(" .:-")
    if iss.get("state") == "closed":
        return "reject", "closed by hand"
    return None, ""


def publish() -> None:
    from pathlib import Path

    cfg = config()
    queue = load("queue.json", {})
    history = load("history.json", [])
    niches = {n["id"]: n for n in load("niches.json", {}).get("active", [])}
    expire = dt.timedelta(days=cfg["review"]["expire_after_days"])
    for vid_id, meta in list(queue.items()):
        try:
            decision, note = _decision(meta)
        except RuntimeError as e:
            print("skip", vid_id, e)
            continue
        rec = {"id": vid_id, "niche": meta["niche"], "kind": meta["kind"], "topic": meta["topic"],
               "title": meta["script"]["title"], "at": now().isoformat()}
        if decision == "approve":
            n = niches.get(meta["niche"])
            if not n:
                continue
            OUT.mkdir(exist_ok=True)
            video = gh.download_asset(meta["asset_id"], OUT / f"{vid_id}.mp4")
            thumb = (gh.download_asset(meta["thumb_asset_id"], OUT / f"{vid_id}.jpg")
                     if meta.get("thumb_asset_id") else None)
            when = publisher.next_slot(meta["niche"], meta["kind"])
            plats = cfg["platforms"]["shorts" if meta["kind"] == "short" else "longform"]
            try:
                res = publisher.post(video, meta, plats, n["upload_post_user"], when, thumb)
            except RuntimeError as e:
                gh.comment(meta["issue"], f"⚠️ Posting failed, will retry next run.\n```\n{e}\n```")
                continue
            rec.update(status="scheduled", scheduled_for=when.isoformat(), platforms=plats,
                       job_id=res.get("job_id"))
            gh.comment(meta["issue"], f"✅ Scheduled for {when:%a %b %d, %H:%M} UTC on {', '.join(plats)}.")
            gh.close(meta["issue"], "posted")
        elif decision == "reject":
            rec.update(status="rejected", reason=note)
            gh.close(meta["issue"], "rejected")
        elif now() - dt.datetime.fromisoformat(meta["created"]) > expire:
            rec.update(status="expired")
            gh.comment(meta["issue"], "⌛ Expired without a decision, so it was not posted.")
            gh.close(meta["issue"], "expired")
        else:
            continue
        gh.delete_asset(meta.get("asset_id"))
        gh.delete_asset(meta.get("thumb_asset_id"))
        history.append(rec)
        queue.pop(vid_id)
    save("queue.json", queue)
    save("history.json", history)


# ------------------------------------------------------------- report


def _link_youtube_ids(history: list[dict]) -> None:
    missing = {h["id"] for h in history if h.get("status") == "scheduled" and not h.get("youtube_id")}
    if not missing:
        return
    try:
        rows = publisher.history_urls()
    except Exception as e:
        print("history lookup failed", e)
        return
    for row in rows:
        blob = json.dumps(row)
        for h in history:
            if h["id"] in missing and h["id"] in blob:
                yid = video_id_from_url(blob)
                if yid:
                    h["youtube_id"] = yid


def report() -> None:
    history = load("history.json", [])
    _link_youtube_ids(history)
    save("history.json", history)
    ids = [h["youtube_id"] for h in history if h.get("youtube_id")]
    stats = video_stats(ids)
    save("stats.json", {"updated": now().isoformat(), "videos": stats})

    state = load("niches.json", {})
    lines, per_niche = [], {}
    for n in state.get("active", []):
        mine = [h for h in history if h["niche"] == n["id"] and h.get("youtube_id") in stats]
        views = sorted(stats[h["youtube_id"]]["viewCount"] for h in mine)
        med = views[len(views) // 2] if views else 0
        per_niche[n["id"]] = (len(mine), med, sum(views))
        top = sorted(mine, key=lambda h: stats[h["youtube_id"]]["viewCount"], reverse=True)[:3]
        lines.append(f"### {n['brand']['channel_name']}\n"
                     f"{len(mine)} videos live · median {med:,} views · total {sum(views):,}\n" +
                     "\n".join(f"- {stats[h['youtube_id']]['viewCount']:,} · {h['title']}" for h in top))

    # Shift effort to the winner once there's enough evidence.
    shift = ""
    if len(per_niche) == 2:
        (a, (na, ma, _)), (b, (nb, mb, _)) = per_niche.items()
        if na >= 30 and nb >= 30 and max(ma, mb) >= 3 * max(min(ma, mb), 1):
            win = a if ma > mb else b
            for n in state["active"]:
                n["weight"] = 2 if n["id"] == win else 0
            save("niches.json", state)
            shift = (f"\n\n**Change:** one niche is outperforming the other 3 to 1 or better after 30+ "
                     f"videos each, so all daily Shorts now go to the winner. The loser is paused, not deleted.")

    statuses = {}
    for h in history:
        if h.get("at", "").startswith(month_key()):
            statuses[h.get("status")] = statuses.get(h.get("status"), 0) + 1
    spend = load("spend.json", {}).get(month_key(), {})
    body = ("\n\n".join(lines) or "No public videos yet.") + shift + f"""

### This month
Posted {statuses.get('scheduled', 0)} · rejected {statuses.get('rejected', 0)} · expired {statuses.get('expired', 0)} · failed fact check {statuses.get('checker_rejected', 0)}
Claude API about ${spend.get('anthropic_usd', 0):.2f} · voice {int(spend.get('elevenlabs_chars', 0)):,} characters

### Money
YouTube ad revenue needs Partner Program eligibility. Affiliate links come from `data/affiliates.json`; the niche's suggested programs are listed in `data/niches.json`.
"""
    gh.create_issue(f"Weekly report {now():%b %d}", body, ["report"])


def _alert(title: str, body: str) -> None:
    gh.create_issue(f"⚠️ {title}", body, ["bot-alert"])
