# blankface

A faceless video channel that mostly runs itself. Every day it writes,
voices, edits and queues Shorts for two niches it picked on its own, then
posts the ones you approve to YouTube and TikTok. Once a week it makes a
longer video and sends you a stats report.

## Your whole job: about 15 minutes a week

Each morning new videos show up as **GitHub issues** (turn on notifications
in the GitHub mobile app). Open one, tap **Watch the video**, then reply:

* `yes` to post it at the next good time slot
* `no` to toss it (add a reason, like `no, boring hook`, and the bot learns)

Ignore one for 5 days and it expires without posting. Nothing goes public
without your yes.

## How it works

| Step | What happens | Runs |
|---|---|---|
| Pick niches | Claude proposes 8 niches, live YouTube data checks whether small channels still break through, the top 2 win | once, by hand |
| Produce | idea, script, separate fact check, AI voice, stock footage, captions, render | daily 4am Central |
| Review | video lands in a GitHub issue for your yes or no | you |
| Publish | approved videos get scheduled through Upload-Post with AI disclosure on | the moment you reply |
| Learn | weekly stats; the idea generator copies winners and avoids flops and your rejections; after 30+ videos per niche, effort shifts to the clear winner | Sundays |

Guardrails: monthly spend caps in `config.yaml`, banned topic areas
(money, health, legal advice, kids, politics), original narration only
(no reused clips), and the fact checker can kill an idea.

## One time setup (about an hour)

**1. Get the keys** (total about $70 a month)

| Service | Plan | Cost | Where |
|---|---|---|---|
| Anthropic API | pay as you go, capped at $25 | about $15 to $25 | console.anthropic.com |
| ElevenLabs | Creator (needs commercial rights) | $22 | elevenlabs.io |
| Upload-Post | Basic | $24 ($16 if paid yearly) | upload-post.com |
| Pexels | free API key | $0 | pexels.com/api |
| YouTube Data API | free API key (read only, for stats) | $0 | console.cloud.google.com, enable "YouTube Data API v3", create an API key |

**2. Add them to this repo:** Settings, then Secrets and variables, then
Actions, then New repository secret. Names must match exactly:

```
ANTHROPIC_API_KEY
ELEVENLABS_API_KEY
UPLOAD_POST_API_KEY
PEXELS_API_KEY
YOUTUBE_API_KEY
```

**3. Let it pick the niches:** Actions tab, then **Pick niches (manual)**,
then Run workflow. It opens an issue with two channel names, bios, and
handle ideas.

**4. Make the accounts:** for each niche, create a YouTube channel and a
TikTok account using the suggested name. In Upload-Post create two profiles
named exactly `niche1` and `niche2` and connect each one's YouTube and
TikTok.

**5. Kick off the first batch:** Actions, then **Produce daily Shorts**, then
Run workflow. After that it runs every day on its own.

**Later, when you have a minute:** sign up for the affiliate programs the
niche issue suggests and add your links to `data/affiliates.json` like
`{"n1": [{"name": "Audible free trial", "url": "https://..."}]}`. The
writer will start mentioning them where they fit.

## Knobs

Everything lives in `config.yaml`: Shorts per day, platforms (add
`instagram` once you connect a Business or Creator Instagram), review
expiry, voice, spend caps, banned topics.

To run locally without any keys: `SHORTS_OFFLINE=1 python run.py produce`
renders a placeholder video so you can see the pipeline work.
