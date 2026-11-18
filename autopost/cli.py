"""Entry point.

python -m autopost build                 write + render + host + schedule today's episodes
python -m autopost tick                  post anything due, refresh stats and tokens
python -m autopost command <cmd> <id>    approve | skip | post_now | retry | mark_published
python -m autopost check                 test every connection, write state/health.json
Flags: --dry-run (no platform calls), --fake-llm <story.json> (no Claude calls; for testing)
"""
import argparse
import datetime as dt
import os
import shutil
import sys
import tempfile
import traceback

import requests

from . import common as C
from . import generate, gh, render, schedule
from .platforms import instagram, tiktok, youtube

PLATFORMS = {"instagram": instagram, "youtube": youtube, "tiktok": tiktok}
MAX_ATTEMPTS = 3


def posts():
    return C.load("state/posts.json", [])


def save_posts(ps):
    C.save("state/posts.json", ps)


def log_run(kind, ok, summary, errors=()):
    r = C.load("state/runs.json", {"runs": []})
    r["runs"] = ([{"kind": kind, "at": C.iso(C.now()), "ok": ok, "summary": summary, "errors": list(errors)[:10]}]
                 + r["runs"])[:60]
    C.save("state/runs.json", r)


# ---------------------------------------------------------------- build

def build_series(series, today, args):
    hist = generate.history(series["id"])
    if any(e.get("date") == today.isoformat() for e in hist["episodes"]):
        C.log(f"{series['id']}: already built today")
        return None
    n = (hist["episodes"][-1]["n"] + 1) if hist["episodes"] else 1
    C.log(f"{series['id']}: writing part {n}")
    if args.fake_llm:
        res = C.load(args.fake_llm)
        res = res if "story" in res else {"story": res, "synopsis": "test episode", "cliffhanger": "?",
                                          "caption": "Test caption. What would you do?", "hashtags": ["aistories"],
                                          "yt_title": "Test episode", "yt_description": "test"}
        res["story"] = generate.normalize(res["story"], series, n)
        errs = generate.validate(res["story"])
        if errs:
            raise C.PostError(f"fake story invalid: {errs}")
    else:
        res = generate.write_episode(series, n, hist)

    story = res["story"]
    mp4 = render.render(story)
    info = render.probe(mp4)
    errs = render.check(info)
    if errs:
        raise C.PostError("; ".join(errs))
    if not args.fake_llm:
        sheet = render.contact_sheet(mp4, info["duration"])
        q = generate.qa(story, sheet)
        if not q["pass"]:
            C.log(f"  QA failed: {q['problems']}; revising once")
            res = generate.revise(series, n, hist, res, q["problems"])
            story = res["story"]
            mp4 = render.render(story)
            info = render.probe(mp4)
            errs = render.check(info)
            if errs:
                raise C.PostError("; ".join(errs))
    thumb = render.thumbnail(mp4)

    tag = f"ep-{today.isoformat()}"
    if args.dry_run:
        video_url, thumb_url = "file://" + mp4, "file://" + thumb
    else:
        video_url = gh.upload(tag, mp4, "video/mp4")
        thumb_url = gh.upload(tag, thumb, "image/jpeg")

    hist["episodes"].append({"n": n, "date": today.isoformat(), "day": f"DAY {n}", "slug": story["slug"],
                             "synopsis": res.get("synopsis", ""), "cliffhanger": res.get("cliffhanger", ""),
                             "duration": info["duration"]})
    C.save(f"state/episodes/{series['id']}.json", hist)
    return {"series": series, "n": n, "res": res, "info": info, "video_url": video_url, "thumb_url": thumb_url}


def cmd_build(args):
    s = C.settings()
    if not args.fake_llm and not os.environ.get("ANTHROPIC_API_KEY"):
        log_run("build", False, "Setup not finished", ["Add your Claude API key in the dashboard Setup tab"])
        C.log("ANTHROPIC_API_KEY not set; skipping build")
        return 0
    today = C.now().astimezone(C.tz()).date()
    active = [x for x in C.series_list() if x.get("active", True)]
    if args.series:
        active = [x for x in active if x["id"] == args.series]
    built, errors = [], []
    for series in active:
        try:
            b = build_series(series, today, args)
            if b:
                built.append(b)
        except Exception as e:  # one series failing must not stop the others
            traceback.print_exc()
            errors.append(f"{series['id']}: {e}")
    ps = posts()
    order = [b["series"]["id"] for b in built]
    if order:
        k = today.toordinal() % len(order)
        order = order[k:] + order[:k]   # rotate so no series always gets the best slot
    plats = [p for p, cfg in s["platforms"].items() if cfg.get("enabled")]
    for plat in plats:
        when = schedule.times_for_day(plat, order, today, ps)
        for b in built:
            sid, r = b["series"]["id"], b["res"]
            ps.append({
                "id": f"{sid}-{b['n']:03d}-{plat}", "series": sid, "series_name": b["series"]["name"],
                "episode": b["n"], "platform": plat, "slug": r["story"]["slug"],
                "status": "pending_approval" if s.get("approval") == "manual" else "scheduled",
                "scheduled_at": C.iso(when[sid]), "video_url": b["video_url"], "thumb_url": b["thumb_url"],
                "duration": b["info"]["duration"], "caption": r.get("caption", ""), "hashtags": r.get("hashtags", []),
                "yt_title": r.get("yt_title", ""), "yt_description": r.get("yt_description", ""),
                "attempts": 0, "created_at": C.iso(C.now())})
    save_posts(ps)
    summary = f"built {len(built)}/{len(active)}: " + ", ".join(f"{b['series']['id']} part {b['n']}" for b in built)
    log_run("build", not errors, summary, errors)
    C.log(summary)
    for e in errors:
        C.log("ERROR", e)
    return 1 if errors and not built else 0


# ---------------------------------------------------------------- tick

def fetch_video(p, cache):
    if p["slug"] in cache:
        return cache[p["slug"]]
    local = os.path.join(C.OUT, f"{p['slug']}.mp4")
    if os.path.exists(local):
        cache[p["slug"]] = local
        return local
    url = p["video_url"]
    if url.startswith("file://"):
        return url[7:]
    d = tempfile.mkdtemp(prefix="vid_")
    out = os.path.join(d, f"{p['slug']}.mp4")
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(out, "wb") as f:
            shutil.copyfileobj(r.raw, f)
    cache[p["slug"]] = out
    return out


def caption_for(p):
    tags = " ".join("#" + t.lstrip("#") for t in p.get("hashtags", []))
    return (p.get("caption", "") + ("\n\n" + tags if tags else "")).strip()[:2200]


def post_one(p, cache, dry):
    item = dict(p, caption=caption_for(p))
    if dry:
        C.log(f"  [dry-run] would post {p['id']}")
        return {"remote_id": "dry-" + p["id"], "url": "", "inbox": p["platform"] == "tiktok" and
                C.settings()["platforms"]["tiktok"].get("mode", "inbox") == "inbox"}
    mp4 = fetch_video(p, cache)
    return PLATFORMS[p["platform"]].post(item, mp4, p.get("video_url"))


def run_due(ps, dry, only=None):
    now = C.now()
    cache, done, errs = {}, [], []
    for p in ps:
        if p["status"] != "scheduled" or (only and p["id"] != only):
            continue
        if C.parse(p["scheduled_at"]) > now and not only:
            continue
        if not C.settings()["platforms"].get(p["platform"], {}).get("enabled"):
            p["status"], p["error"] = "skipped", "platform disabled"
            continue
        C.log(f"posting {p['id']}")
        p["attempts"] = p.get("attempts", 0) + 1
        try:
            r = post_one(p, cache, dry)
            p.update(remote_id=r.get("remote_id"), url=r.get("url", ""), posted_at=C.iso(C.now()), error="")
            if r.get("warning"):
                p["warning"] = r["warning"]
            p["status"] = "inbox" if r.get("inbox") else "posted"
            done.append(p["id"])
        except Exception as e:
            msg = str(e)[:400]
            p["error"] = msg
            if p["attempts"] >= MAX_ATTEMPTS:
                p["status"] = "failed"
            else:
                p["scheduled_at"] = C.iso(now + dt.timedelta(minutes=45))
            errs.append(f"{p['id']}: {msg}")
            C.log("  FAILED", msg)
    return done, errs


def refresh_metrics(ps, dry, limit=40):
    if dry:
        return 0
    now, n = C.now(), 0
    tt_recent = None
    for p in ps:
        if n >= limit or p["status"] not in ("posted", "inbox") or not p.get("posted_at"):
            continue
        age = now - C.parse(p["posted_at"])
        last = C.parse(p["metrics_at"]) if p.get("metrics_at") else None
        if age < dt.timedelta(hours=1) or age > dt.timedelta(days=14) or (last and now - last < dt.timedelta(hours=6)):
            continue
        try:
            if p["platform"] == "tiktok" and not str(p.get("remote_id", "")).isdigit():
                tt_recent = tt_recent if tt_recent is not None else tiktok.recent_videos()
                taken = {q.get("remote_id") for q in ps}
                t0 = C.parse(p["posted_at"]).timestamp()
                match = [v for v in tt_recent if str(v["id"]) not in taken and 0 <= v.get("create_time", 0) - t0 < 86400 * 2]
                if not match:
                    continue
                v = min(match, key=lambda v: v["create_time"])
                p.update(remote_id=str(v["id"]), url=v.get("share_url", ""), status="posted",
                         posted_at=C.iso(dt.datetime.fromtimestamp(v["create_time"], dt.timezone.utc)))
            m = PLATFORMS[p["platform"]].metrics(p["remote_id"])
            if m:
                p["metrics"], p["metrics_at"] = m, C.iso(now)
                n += 1
        except Exception as e:
            C.log(f"  metrics {p['id']}: {e}")
    return n


def refresh_tokens(dry):
    if dry or not os.environ.get("IG_ACCESS_TOKEN"):
        return
    t = C.load("state/tokens.json", {})
    last = C.parse(t["instagram_refreshed"]) if t.get("instagram_refreshed") else None
    if last and C.now() - last < dt.timedelta(days=7):
        return
    try:
        instagram.refresh()
        t["instagram_refreshed"] = C.iso(C.now())
        C.save("state/tokens.json", t)
    except Exception as e:
        C.log(f"  instagram token refresh failed: {e}")


def cmd_tick(args):
    ps = posts()
    done, errs = run_due(ps, args.dry_run)
    save_posts(ps)
    refresh_tokens(args.dry_run)
    m = refresh_metrics(ps, args.dry_run)
    save_posts(ps)
    C.save("state/best_hours.json", schedule.best_hours_report(ps))
    if done or errs:
        log_run("post", not errs, f"posted {len(done)}" + (f", {m} stats updated" if m else ""), errs)
    C.log(f"tick: posted {len(done)}, errors {len(errs)}, stats {m}")
    return 0


def cmd_command(args):
    ps = posts()
    p = next((x for x in ps if x["id"] == args.post_id), None)
    if not p:
        C.log(f"no post {args.post_id}")
        return 1
    c = args.cmd
    if c == "approve" and p["status"] == "pending_approval":
        p["status"] = "scheduled"
    elif c == "skip":
        p["status"] = "skipped"
    elif c in ("post_now", "retry"):
        p.update(status="scheduled", scheduled_at=C.iso(C.now()), attempts=0 if c == "retry" else p.get("attempts", 0))
        save_posts(ps)
        done, errs = run_due(ps, args.dry_run, only=p["id"])
        log_run("post", not errs, f"{c} {p['id']}", errs)
    elif c == "mark_published":
        p.update(status="posted", posted_at=p.get("posted_at") or C.iso(C.now()))
    else:
        C.log(f"command {c} not valid for status {p['status']}")
        return 1
    save_posts(ps)
    return 0


def cmd_check(args):
    """Test each platform connection and the Claude key. Writes state/health.json for the dashboard."""
    h = {"at": C.iso(C.now())}

    def t(name, fn):
        try:
            h[name] = {"ok": True, "detail": fn()}
        except Exception as e:
            h[name] = {"ok": False, "detail": str(e)[:300]}

    if os.environ.get("IG_ACCESS_TOKEN"):
        t("instagram", lambda: f"user {instagram.user_id()}, quota {instagram.quota()}")
    else:
        h["instagram"] = {"ok": False, "detail": "IG_ACCESS_TOKEN not set"}
    if os.environ.get("YT_REFRESH_TOKEN"):
        def yt():
            r = requests.get("https://www.googleapis.com/youtube/v3/channels", params={"part": "snippet", "mine": "true"},
                             headers={"Authorization": f"Bearer {youtube.access_token()}"}, timeout=30)
            r.raise_for_status()
            items = r.json().get("items", [])
            return "channel " + (items[0]["snippet"]["title"] if items else "none found")
        t("youtube", yt)
    else:
        h["youtube"] = {"ok": False, "detail": "YT_REFRESH_TOKEN not set"}
    if os.environ.get("TT_REFRESH_TOKEN"):
        def tt():
            r = requests.get(f"{tiktok.API}/v2/user/info/", params={"fields": "display_name"},
                             headers={"Authorization": f"Bearer {tiktok.access_token()}"}, timeout=30)
            r.raise_for_status()
            return "user " + str(r.json().get("data", {}).get("user", {}).get("display_name"))
        t("tiktok", tt)
    else:
        h["tiktok"] = {"ok": False, "detail": "TT_REFRESH_TOKEN not set"}
    h["claude"] = {"ok": bool(os.environ.get("ANTHROPIC_API_KEY")), "detail": "key set" if os.environ.get("ANTHROPIC_API_KEY") else "ANTHROPIC_API_KEY not set"}
    C.save("state/health.json", h)
    C.log(h)
    return 0


def cmd_connect(args):
    """Finish a phone sign-in: trade the one-time OAUTH_CODE secret for a long-lived refresh token."""
    code = C.secret("OAUTH_CODE")
    prov, redirect = args.provider, args.redirect
    if prov == "youtube":
        r = requests.post("https://oauth2.googleapis.com/token", timeout=30, data={
            "code": code, "client_id": C.secret("YT_CLIENT_ID"), "client_secret": C.secret("YT_CLIENT_SECRET"),
            "redirect_uri": redirect, "grant_type": "authorization_code"})
        j = r.json() if r.content else {}
        name, tok = "YT_REFRESH_TOKEN", j.get("refresh_token")
    elif prov == "tiktok":
        r = requests.post("https://open.tiktokapis.com/v2/oauth/token/", timeout=30,
                          headers={"Content-Type": "application/x-www-form-urlencoded"},
                          data={"client_key": C.secret("TT_CLIENT_KEY"), "client_secret": C.secret("TT_CLIENT_SECRET"),
                                "code": code, "grant_type": "authorization_code", "redirect_uri": redirect})
        j = r.json() if r.content else {}
        name, tok = "TT_REFRESH_TOKEN", j.get("refresh_token")
    else:
        raise SystemExit(f"unknown provider {prov}")
    h = C.load("state/health.json", {})
    if not tok:
        err = j.get("error_description") or j.get("error") or r.text[:300]
        h[prov] = {"ok": False, "detail": f"sign-in failed: {err}"}
        C.save("state/health.json", h)
        log_run("connect", False, f"{prov} sign-in failed", [str(err)])
        return 1
    if not gh.set_secret(name, tok):
        raise SystemExit("GH_PAT missing: cannot save the token")
    gh.set_secret("OAUTH_CODE", "used")
    log_run("connect", True, f"{prov} connected")
    return cmd_check(args)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="autopost")
    sub = ap.add_subparsers(dest="cmd_name", required=True)
    b = sub.add_parser("build")
    b.add_argument("--series")
    b.add_argument("--fake-llm")
    t = sub.add_parser("tick")
    k = sub.add_parser("check")
    cn = sub.add_parser("connect")
    cn.add_argument("provider", choices=["youtube", "tiktok"])
    cn.add_argument("--redirect", required=True)
    c = sub.add_parser("command")
    c.add_argument("cmd", choices=["approve", "skip", "post_now", "retry", "mark_published"])
    c.add_argument("post_id")
    for p in (b, t, c, k, cn):
        p.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    return {"build": cmd_build, "tick": cmd_tick, "command": cmd_command, "check": cmd_check, "connect": cmd_connect}[args.cmd_name](args)


if __name__ == "__main__":
    sys.exit(main())
