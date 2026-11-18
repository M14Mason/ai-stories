# AI Stories autopilot

Every night GitHub writes, renders and schedules one new episode per series, then posts each one
to Instagram Reels, YouTube Shorts and TikTok at its own time. Your computer can be off.
You control it from a phone dashboard.

```
2 AM build (GitHub Actions)              hourly tick (GitHub Actions)
  Claude writes part N of each series      posts anything due
  validator + fix loop                     retries failures (3 tries)
  render with the /video engine            pulls views/likes
  Claude checks the frames                 learns best hours
  video hosted on GitHub Releases          refreshes tokens
  posts scheduled at learned times
                 \                          /
                  state/*.json  <->  phone dashboard (GitHub Pages)
```

## What it costs
- GitHub Actions, Pages, Releases: free on a public repo.
- Claude API: my estimate is $10 to $20 a month for 3 episodes a day. Builds stop at the budget you set.
- Instagram, YouTube, TikTok APIs: free.

## Setup (about 1 hour, mostly on your phone)

1. **Turn on Pages:** repo Settings > Pages > Deploy from a branch > `main` / `/docs` > Save. Wait 1 minute.
2. **Make one GitHub token:** github.com/settings/personal-access-tokens/new. Only this repo. Permissions **Actions**, **Contents**, **Secrets**: Read and write.
3. **Open the dashboard:** `https://<you>.github.io/ai-stories/`. Paste the token. Share > Add to Home Screen.
4. **Follow the Setup tab.** Six steps, each with links and a Save button. Keys are encrypted on your phone and stored as GitHub secrets:
   - Claude key
   - Instagram token (from Meta's dashboard)
   - YouTube: paste client ID/secret, tap Sign in with Google
   - TikTok: paste client key/secret, tap Sign in with TikTok
   - Test connections, then Build first episode and use Post now

The terminal scripts in `scripts/auth_*.py` are a backup if a phone sign-in fails.

## Daily use
- Nothing. It builds at about 2 AM Pacific and posts through the day.
- Turn on **Ask before posting** in System if you want to approve each post.
- Add or edit series in the Series tab. Changes apply to the next episode.

## Files
- `config/series.json` your series. `config/settings.json` schedule slots, budget, model.
- `prompts/system.md` the writing rules Claude follows (taken from your /video skill). Edit to change the style.
- `state/` everything the bot remembers. Do not edit by hand while a run is going.
- `engine/` the /video render engine. `autopost/` the pipeline. `docs/` the dashboard.

## Tests
`python3 -m pytest tests` (offline, all platform calls mocked).
`node tests/dashboard_test.cjs` (needs puppeteer-core and Chrome).
