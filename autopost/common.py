"""Shared helpers: paths, JSON state, time, logging."""
import json
import os
import sys
import datetime as dt
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config")
STATE = os.path.join(ROOT, "state")
OUT = os.path.join(ROOT, "out")
STORIES = os.path.join(ROOT, "stories")


def path(*p):
    return os.path.join(ROOT, *p)


def load(rel, default=None):
    p = rel if os.path.isabs(rel) else path(rel)
    if not os.path.exists(p):
        return default
    with open(p) as f:
        return json.load(f)


def save(rel, data):
    p = rel if os.path.isabs(rel) else path(rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, p)


def settings():
    return load("config/settings.json")


def series_list():
    return load("config/series.json", [])


def tz():
    return ZoneInfo(settings().get("timezone", "America/Los_Angeles"))


def now():
    """Current time, timezone aware (UTC). AUTOPOST_NOW overrides it for tests."""
    fake = os.environ.get("AUTOPOST_NOW")
    if fake:
        return dt.datetime.fromisoformat(fake).astimezone(dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)


def iso(t):
    return t.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def parse(s):
    return dt.datetime.fromisoformat(s)


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def secret(name, required=True):
    v = os.environ.get(name, "").strip()
    if required and not v:
        raise RuntimeError(f"missing secret {name}")
    return v


class PostError(Exception):
    """A platform refused or failed a post. Message is shown on the dashboard."""
