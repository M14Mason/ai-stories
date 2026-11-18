"""Offline tests: every platform call is mocked, so these prove our request flow, not the platforms."""
import json
import os
import re
import shutil

import pytest
import responses

from autopost import common as C
from autopost import cli, generate, schedule
from autopost.platforms import instagram, tiktok, youtube


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    """Run against a copy of config/ and an empty state/ so the real repo is untouched."""
    root = tmp_path / "repo"
    for d in ("config", "prompts", "engine", "sfx"):
        shutil.copytree(os.path.join(C.ROOT, d), root / d)
    (root / "state" / "episodes").mkdir(parents=True)
    (root / "state" / "posts.json").write_text("[]")
    monkeypatch.setattr(C, "ROOT", str(root))
    monkeypatch.setattr(C, "OUT", str(root / "out"))
    monkeypatch.setattr(C, "STORIES", str(root / "stories"))
    monkeypatch.setenv("AUTOPOST_NOW", "2026-11-18T21:00:00+00:00")
    for k in ("GH_PAT",):
        monkeypatch.delenv(k, raising=False)
    tiktok._cache.clear(); youtube._cache.clear()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00" * 2048)
    return video


def story():
    return json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "story_zombie.json")))


# ------------------------------------------------------------ generator

def test_example_story_valid():
    assert generate.validate(story()) == []


def test_validator_catches_problems():
    s = story()
    s["scenes"][-1].pop("ask")
    s["scenes"][1]["build"] = "return `${Math.random()}`;"
    s["scenes"][2]["anim"] = "tl.to('#x',{x:1},S"   # syntax error
    s["scenes"][3]["sfx"] = [{"id": "nope"}]
    errs = " | ".join(generate.validate(s))
    assert "ask" in errs and "Math.random" in errs and "JavaScript" in errs and "unknown sfx" in errs


def test_write_episode_retries_with_errors(monkeypatch):
    bad = {"story": dict(story(), scenes=story()["scenes"][:-1])}
    good = {"story": story(), "synopsis": "s", "cliffhanger": "c", "caption": "c", "hashtags": ["a"], "yt_title": "t"}
    replies = iter(["sure! " + json.dumps(bad), "```json\n" + json.dumps(good) + "\n```"])
    seen = []
    monkeypatch.setattr("autopost.llm.ask", lambda system, msgs, purpose, **k: (seen.append(msgs[-1]["content"]), next(replies))[1])
    series = C.series_list()[0]
    res = generate.write_episode(series, 2, generate.history(series["id"]))
    assert res["story"]["slug"] == "homedepot_ep002" and res["story"]["hud"]["day"] == "DAY 2"
    assert "Fix these problems" in seen[1] and "ask" in seen[1]


def test_budget_guard(monkeypatch):
    from autopost import llm
    C.save("state/usage.json", {llm.month_key(): {"usd": 99}})
    with pytest.raises(C.PostError, match="budget"):
        llm.check_budget()


# ------------------------------------------------------------ scheduler

def test_default_slots_distinct_and_gapped():
    import datetime as dt
    t = schedule.times_for_day("instagram", ["a", "b", "c"], dt.date(2026, 11, 18), [])
    hours = sorted(v.hour for v in t.values())
    assert len(set(hours)) == 3 and all(b - a >= 2 for a, b in zip(hours, hours[1:]))


def test_learning_prefers_best_hour(monkeypatch):
    monkeypatch.setattr(schedule, "_rand", lambda k: 0.99)  # never explore
    posts = []
    for i in range(10):
        for h, views in ((12, 100), (19, 400), (15, 100)):
            posts.append({"platform": "instagram", "series": "a", "status": "posted",
                          "posted_at": f"2026-11-{i+1:02d}T{h:02d}:10:00-08:00", "metrics": {"views": views}})
    assert schedule.pick_hours("instagram", 1, "x", posts) == [19]


# ------------------------------------------------------------ platforms (mocked)

@responses.activate
def test_instagram_resumable_flow(sandbox, monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok"); monkeypatch.setenv("IG_USER_ID", "123")
    monkeypatch.setattr("time.sleep", lambda s: None)
    G = "https://graph.instagram.com/v23.0"
    responses.post(f"{G}/123/media", json={"id": "C1", "uri": "https://rupload.facebook.com/ig-api-upload/v23.0/C1"})
    responses.post("https://rupload.facebook.com/ig-api-upload/v23.0/C1", json={"success": True})
    responses.get(f"{G}/C1", json={"status_code": "IN_PROGRESS"})
    responses.get(f"{G}/C1", json={"status_code": "FINISHED"})
    responses.post(f"{G}/123/media_publish", json={"id": "M9"})
    responses.get(f"{G}/M9", json={"permalink": "https://instagram.com/reel/x"})
    r = instagram.post({"caption": "hi"}, str(sandbox))
    assert r == {"remote_id": "M9", "url": "https://instagram.com/reel/x"}
    up = responses.calls[1].request
    assert up.headers["Authorization"] == "OAuth tok" and up.headers["file_size"] == "2048"


@responses.activate
def test_instagram_falls_back_to_url(sandbox, monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok"); monkeypatch.setenv("IG_USER_ID", "123")
    monkeypatch.setattr("time.sleep", lambda s: None)
    G = "https://graph.instagram.com/v23.0"
    responses.post(f"{G}/123/media", json={"error": {"message": "resumable not allowed"}}, status=400)
    responses.post(f"{G}/123/media", json={"id": "C2"})
    responses.get(f"{G}/C2", json={"status_code": "FINISHED"})
    responses.post(f"{G}/123/media_publish", json={"id": "M2"})
    responses.get(f"{G}/M2", json={"permalink": ""})
    r = instagram.post({"caption": "hi"}, str(sandbox), "https://example.com/v.mp4")
    assert r["remote_id"] == "M2" and "video_url=https" in responses.calls[1].request.body


@responses.activate
def test_instagram_error_message(sandbox, monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok"); monkeypatch.setenv("IG_USER_ID", "123")
    responses.post("https://graph.instagram.com/v23.0/123/media", json={"error": {"message": "Invalid OAuth access token"}}, status=400)
    with pytest.raises(C.PostError, match="Invalid OAuth"):
        instagram.post({"caption": "hi"}, str(sandbox))


@responses.activate
def test_youtube_upload(sandbox, monkeypatch):
    for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
        monkeypatch.setenv(k, "x")
    responses.post("https://oauth2.googleapis.com/token", json={"access_token": "AT"})
    responses.post("https://www.googleapis.com/upload/youtube/v3/videos", headers={"Location": "https://up.example/1"})
    responses.put("https://up.example/1", json={"id": "VID", "status": {"privacyStatus": "public"}})
    r = youtube.post({"caption": "c", "yt_title": "Day two at the store", "hashtags": ["a"]}, str(sandbox))
    assert r["url"] == "https://youtube.com/shorts/VID" and "warning" not in r
    meta = json.loads(responses.calls[1].request.body)
    assert meta["snippet"]["title"].endswith("#Shorts") and meta["status"]["containsSyntheticMedia"] is True


@responses.activate
def test_youtube_private_warning(sandbox, monkeypatch):
    for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
        monkeypatch.setenv(k, "x")
    responses.post("https://oauth2.googleapis.com/token", json={"access_token": "AT"})
    responses.post("https://www.googleapis.com/upload/youtube/v3/videos", headers={"Location": "https://up.example/1"})
    responses.put("https://up.example/1", json={"id": "VID", "status": {"privacyStatus": "private"}})
    assert "audit" in youtube.post({"caption": "c"}, str(sandbox))["warning"]


@responses.activate
def test_tiktok_inbox_and_token_rotation(sandbox, monkeypatch):
    for k, v in (("TT_CLIENT_KEY", "k"), ("TT_CLIENT_SECRET", "s"), ("TT_REFRESH_TOKEN", "old")):
        monkeypatch.setenv(k, v)
    monkeypatch.setattr("time.sleep", lambda s: None)
    saved = {}
    monkeypatch.setattr("autopost.gh.set_secret", lambda n, v: saved.update({n: v}))
    A = "https://open.tiktokapis.com"
    responses.post(f"{A}/v2/oauth/token/", json={"access_token": "AT", "refresh_token": "new"})
    responses.post(f"{A}/v2/post/publish/inbox/video/init/", json={"data": {"publish_id": "P1", "upload_url": "https://up.tt/1"}, "error": {"code": "ok"}})
    responses.put("https://up.tt/1", status=201)
    responses.post(f"{A}/v2/post/publish/status/fetch/", json={"data": {"status": "PROCESSING_UPLOAD"}, "error": {"code": "ok"}})
    responses.post(f"{A}/v2/post/publish/status/fetch/", json={"data": {"status": "SEND_TO_USER_INBOX"}, "error": {"code": "ok"}})
    r = tiktok.post({"caption": "c"}, str(sandbox))
    assert r == {"remote_id": "P1", "url": "", "inbox": True}
    assert saved == {"TT_REFRESH_TOKEN": "new"}
    assert responses.calls[2].request.headers["Content-Range"] == "bytes 0-2047/2048"


@responses.activate
def test_tiktok_unaudited_error(sandbox, monkeypatch):
    for k in ("TT_CLIENT_KEY", "TT_CLIENT_SECRET", "TT_REFRESH_TOKEN"):
        monkeypatch.setenv(k, "x")
    A = "https://open.tiktokapis.com"
    responses.post(f"{A}/v2/oauth/token/", json={"access_token": "AT", "refresh_token": "x"})
    responses.post(f"{A}/v2/post/publish/inbox/video/init/", status=403,
                   json={"error": {"code": "unaudited_client_can_only_post_to_private_accounts", "message": "private only"}})
    with pytest.raises(C.PostError, match="unaudited"):
        tiktok.post({"caption": "c"}, str(sandbox))


def test_secret_encryption_roundtrip(monkeypatch):
    """set_secret must produce a sealed box GitHub can open with the repo key."""
    from nacl import encoding, public
    import base64
    from autopost import gh
    sk = public.PrivateKey.generate()
    pk = sk.public_key.encode(encoding.Base64Encoder()).decode()
    sent = {}

    class R:
        def __init__(self, j=None): self._j = j or {}
        def raise_for_status(self): pass
        def json(self): return self._j

    monkeypatch.setenv("GH_PAT", "pat"); monkeypatch.setenv("GITHUB_REPOSITORY", "me/repo")
    monkeypatch.setattr("requests.get", lambda *a, **k: R({"key": pk, "key_id": "K1"}))
    monkeypatch.setattr("requests.put", lambda url, **k: (sent.update(k["json"]), R())[1])
    assert gh.set_secret("TT_REFRESH_TOKEN", "hello")
    plain = public.SealedBox(sk).decrypt(base64.b64decode(sent["encrypted_value"])).decode()
    assert plain == "hello" and sent["key_id"] == "K1"


# ------------------------------------------------------------ cli flow

def seed_posts(sandbox, **over):
    p = {"id": "homedepot-002-instagram", "series": "homedepot", "series_name": "H", "episode": 2,
         "platform": "instagram", "slug": "homedepot_ep002", "status": "scheduled",
         "scheduled_at": "2026-11-18T20:00:00+00:00", "video_url": "file://" + str(sandbox),
         "caption": "Cap", "hashtags": ["a", "b"], "attempts": 0}
    p.update(over)
    C.save("state/posts.json", [p])


def test_tick_posts_due_and_retries(sandbox, monkeypatch):
    seed_posts(sandbox)
    calls = []

    def boom(item, mp4, url=None):
        calls.append(item["caption"])
        raise C.PostError("Instagram publish: server busy")
    monkeypatch.setattr(instagram, "post", boom)
    cli.main(["tick"])
    p = C.load("state/posts.json")[0]
    assert calls == ["Cap\n\n#a #b"] and p["status"] == "scheduled" and p["attempts"] == 1 and "busy" in p["error"]
    assert p["scheduled_at"] > "2026-11-18T21:00"   # pushed back for retry
    monkeypatch.setenv("AUTOPOST_NOW", "2026-11-18T23:00:00+00:00")
    monkeypatch.setattr(instagram, "post", lambda item, mp4, url=None: {"remote_id": "M1", "url": "u"})
    cli.main(["tick"])
    p = C.load("state/posts.json")[0]
    assert p["status"] == "posted" and p["remote_id"] == "M1" and p["error"] == ""


def test_tick_gives_up_after_three(sandbox, monkeypatch):
    seed_posts(sandbox, attempts=2)
    monkeypatch.setattr(instagram, "post", lambda *a, **k: (_ for _ in ()).throw(C.PostError("nope")))
    cli.main(["tick"])
    assert C.load("state/posts.json")[0]["status"] == "failed"


def test_future_post_not_sent(sandbox, monkeypatch):
    seed_posts(sandbox, scheduled_at="2026-11-19T01:00:00+00:00")
    monkeypatch.setattr(instagram, "post", lambda *a, **k: pytest.fail("posted early"))
    cli.main(["tick"])
    assert C.load("state/posts.json")[0]["status"] == "scheduled"


def test_commands(sandbox, monkeypatch):
    seed_posts(sandbox, status="pending_approval", scheduled_at="2026-11-19T01:00:00+00:00")
    cli.main(["command", "approve", "homedepot-002-instagram"])
    assert C.load("state/posts.json")[0]["status"] == "scheduled"
    monkeypatch.setattr(instagram, "post", lambda *a, **k: {"remote_id": "M5", "url": ""})
    cli.main(["command", "post_now", "homedepot-002-instagram"])
    assert C.load("state/posts.json")[0]["status"] == "posted"


def test_metrics_and_tiktok_match(sandbox, monkeypatch):
    C.save("state/posts.json", [
        {"id": "a-ig", "series": "a", "platform": "instagram", "status": "posted", "remote_id": "M1",
         "posted_at": "2026-11-17T20:00:00+00:00", "slug": "a", "scheduled_at": "2026-11-17T20:00:00+00:00"},
        {"id": "a-tt", "series": "a", "platform": "tiktok", "status": "inbox", "remote_id": "P1",
         "posted_at": "2026-11-17T20:00:00+00:00", "slug": "a", "scheduled_at": "2026-11-17T20:00:00+00:00"}])
    monkeypatch.setattr(instagram, "metrics", lambda rid: {"views": 500, "likes": 20})
    monkeypatch.setattr(tiktok, "recent_videos", lambda: [{"id": 777, "create_time": 1794945600 + 3600, "share_url": "s"}])
    monkeypatch.setattr(tiktok, "metrics", lambda rid: {"views": 90} if rid == "777" else {})
    monkeypatch.setattr(cli, "refresh_tokens", lambda dry: None)
    cli.main(["tick"])
    ps = {p["id"]: p for p in C.load("state/posts.json")}
    assert ps["a-ig"]["metrics"]["views"] == 500
    assert ps["a-tt"]["status"] == "posted" and ps["a-tt"]["remote_id"] == "777" and ps["a-tt"]["metrics"]["views"] == 90
    assert "instagram" in C.load("state/best_hours.json")
