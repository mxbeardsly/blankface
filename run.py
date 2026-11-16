"""Entry point. Usage: python run.py {scout|produce|produce-long|publish|report}"""
import sys

from engine import niche_scout, pipeline

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "produce"
    if cmd == "scout":
        s = niche_scout.run(force=True)
        from engine import github as gh
        gh.ensure_labels()
        parts = []
        for n in s["active"]:
            b = n["brand"]
            parts.append(
                f"## {b['channel_name']}  (score {n['total_score']}/100)\n"
                f"**Niche:** {n['name']}: {n['angle']}\n**Audience:** {n['audience']}\n"
                f"**Handle ideas:** {', '.join(b['handle_ideas'])}\n**Bio:** {b['bio']}\n"
                f"**Affiliate programs to join later:** {', '.join(n['affiliate_programs'])}\n"
                f"**Upload-Post profile name to create:** `{n['upload_post_user']}`")
            print(n["id"], n["name"], n["total_score"], b["channel_name"])
        runners = "\n".join(f"- {c['name']} ({c['total_score']})" for c in s["candidates"][len(s["active"]):])
        gh.create_issue("Niches picked: set up these channels", "\n\n".join(parts) +
                        "\n\n**Runners up:**\n" + runners +
                        "\n\nCreate a YouTube channel and TikTok account for each, connect them to the "
                        "matching Upload-Post profile, then close this issue.", ["bot-alert"])
    elif cmd == "produce":
        pipeline.produce("short")
    elif cmd == "produce-long":
        pipeline.produce("long")
    elif cmd == "publish":
        pipeline.publish()
    elif cmd == "report":
        pipeline.report()
    else:
        raise SystemExit(__doc__)
