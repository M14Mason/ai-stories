"""Pick posting times per series and platform, and learn better slots from results.

Score of a slot = shrunk mean of (views of a post / median views of its series on that platform).
Most of the time we take the best distinct slots; sometimes we explore a different one.
Until there is data, default_slots in settings are used (a guess, not research).
"""
import datetime as dt
import hashlib
import statistics

from . import common as C

PRIOR_WEIGHT = 3.0


def slot_scores(posts, platform):
    by_series = {}
    for p in posts:
        v = (p.get("metrics") or {}).get("views")
        if p["platform"] == platform and p.get("status") == "posted" and isinstance(v, (int, float)):
            by_series.setdefault(p["series"], []).append(p)
    agg = {}
    for sid, ps in by_series.items():
        med = statistics.median([q["metrics"]["views"] for q in ps]) or 1
        for q in ps:
            h = C.parse(q["posted_at"]).astimezone(C.tz()).hour
            agg.setdefault(h, []).append(q["metrics"]["views"] / med)
    return {h: (sum(v) + PRIOR_WEIGHT) / (len(v) + PRIOR_WEIGHT) for h, v in agg.items()}, {h: len(v) for h, v in agg.items()}


def _rand(key):
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def pick_hours(platform, n, day_key, posts):
    s = C.settings()
    cands = s["slots"][platform]
    scores, counts = slot_scores(posts, platform)
    gap = s.get("min_gap_hours", 2)
    if sum(counts.values()) < 6:
        ranked = s["default_slots"][platform] + [h for h in cands if h not in s["default_slots"][platform]]
    else:
        ranked = sorted(cands, key=lambda h: -scores.get(h, 1.0))
    chosen = []
    for i in range(n):
        explore = _rand(f"{day_key}:{platform}:{i}") < s.get("explore_rate", 0.2)
        pool = [h for h in ranked if all(abs(h - c) >= gap for c in chosen)] or ranked
        if explore and len(pool) > 1:
            h = pool[int(_rand(f"{day_key}:{platform}:{i}:x") * len(pool)) % len(pool)]
        else:
            h = pool[0]
        chosen.append(h)
    return chosen


def times_for_day(platform, series_ids, day, posts):
    """Return {series_id: aware datetime} for a local calendar day."""
    hours = pick_hours(platform, len(series_ids), day.isoformat(), posts)
    out = {}
    for i, (sid, h) in enumerate(zip(series_ids, hours)):
        minute = int(_rand(f"{day}:{platform}:{sid}:m") * 50) + 3
        out[sid] = dt.datetime.combine(day, dt.time(h, minute), tzinfo=C.tz())
    return out


def best_hours_report(posts):
    rep = {}
    for plat in C.settings()["slots"]:
        sc, ct = slot_scores(posts, plat)
        rep[plat] = [{"hour": h, "score": round(sc[h], 3), "posts": ct[h]} for h in sorted(sc)]
    return rep
