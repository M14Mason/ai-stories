"""TikTok via the official Content Posting API.

mode "inbox" (default): video lands in your TikTok inbox as a draft; you open TikTok,
paste the caption (copy button on the dashboard) and tap Post. Works before TikTok's audit.
mode "direct": publishes directly. Only use after your app passes TikTok's audit,
otherwise TikTok forces posts to private.

Secrets: TT_CLIENT_KEY, TT_CLIENT_SECRET, TT_REFRESH_TOKEN (from scripts/auth_tiktok.py).
"""
import os
import time

import requests

from .. import common as C
from .. import gh

API = "https://open.tiktokapis.com"
_cache = {}


def access_token():
    if "t" in _cache:
        return _cache["t"]
    r = requests.post(f"{API}/v2/oauth/token/", timeout=30,
                      headers={"Content-Type": "application/x-www-form-urlencoded"},
                      data={"client_key": C.secret("TT_CLIENT_KEY"), "client_secret": C.secret("TT_CLIENT_SECRET"),
                            "grant_type": "refresh_token", "refresh_token": C.secret("TT_REFRESH_TOKEN")})
    j = r.json() if r.content else {}
    if r.status_code != 200 or "access_token" not in j:
        raise C.PostError(f"TikTok auth failed: {j.get('error_description') or r.text[:300]} (re-run scripts/auth_tiktok.py)")
    if j.get("refresh_token") and j["refresh_token"] != os.environ.get("TT_REFRESH_TOKEN"):
        gh.set_secret("TT_REFRESH_TOKEN", j["refresh_token"])
    _cache["t"] = j["access_token"]
    return _cache["t"]


def _call(path, body):
    r = requests.post(f"{API}{path}", json=body, timeout=60,
                      headers={"Authorization": f"Bearer {access_token()}", "Content-Type": "application/json; charset=UTF-8"})
    j = r.json() if r.content else {}
    err = j.get("error", {})
    if r.status_code >= 400 or (err.get("code") not in (None, "ok")):
        raise C.PostError(f"TikTok {path}: {err.get('code')} {err.get('message', r.text[:200])}")
    return j.get("data", {})


def _upload(upload_url, mp4):
    size = os.path.getsize(mp4)
    with open(mp4, "rb") as f:
        r = requests.put(upload_url, data=f, timeout=900, headers={
            "Content-Type": "video/mp4", "Content-Length": str(size), "Content-Range": f"bytes 0-{size - 1}/{size}"})
    if r.status_code not in (200, 201):
        raise C.PostError(f"TikTok upload failed: {r.status_code} {r.text[:200]}")


def _source(mp4):
    size = os.path.getsize(mp4)
    if size > 64 * 1024 * 1024:
        raise C.PostError("video over 64 MB; single-chunk upload not supported")
    return {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}


def _status(publish_id, want, timeout=300):
    t0 = time.time()
    last = {}
    while time.time() - t0 < timeout:
        last = _call("/v2/post/publish/status/fetch/", {"publish_id": publish_id})
        st = last.get("status")
        if st in want:
            return last
        if st == "FAILED":
            raise C.PostError(f"TikTok processing failed: {last.get('fail_reason')}")
        time.sleep(8)
    raise C.PostError(f"TikTok status timed out (last {last.get('status')})")


def post(item, mp4, video_url=None):
    mode = C.settings()["platforms"]["tiktok"].get("mode", "inbox")
    if mode == "direct":
        info = _call("/v2/post/publish/creator_info/query/", {})
        opts = info.get("privacy_level_options", [])
        privacy = "PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in opts else (opts[0] if opts else "SELF_ONLY")
        cap = (item["caption"] + " " + " ".join("#" + t for t in item.get("hashtags", []))).strip()[:2200]
        d = _call("/v2/post/publish/video/init/", {
            "post_info": {"title": cap, "privacy_level": privacy, "disable_comment": False,
                          "disable_duet": False, "disable_stitch": False, "is_aigc": True},
            "source_info": _source(mp4)})
        _upload(d["upload_url"], mp4)
        s = _status(d["publish_id"], {"PUBLISH_COMPLETE"})
        ids = s.get("publicaly_available_post_id") or s.get("publicly_available_post_id") or []
        res = {"remote_id": str(ids[0]) if ids else d["publish_id"], "url": ""}
        if privacy != "PUBLIC_TO_EVERYONE":
            res["warning"] = f"posted as {privacy}: app not audited yet"
        return res
    d = _call("/v2/post/publish/inbox/video/init/", {"source_info": _source(mp4)})
    _upload(d["upload_url"], mp4)
    _status(d["publish_id"], {"SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"})
    return {"remote_id": d["publish_id"], "url": "", "inbox": True}


def metrics(remote_id):
    """Needs scope video.list and a real video id (direct mode). Inbox drafts have no stats until you publish."""
    if not remote_id.isdigit():
        return {}
    d = _call("/v2/video/query/?fields=id,view_count,like_count,comment_count,share_count",
              {"filters": {"video_ids": [remote_id]}})
    v = (d.get("videos") or [{}])[0]
    return {"views": v.get("view_count"), "likes": v.get("like_count"),
            "comments": v.get("comment_count"), "shares": v.get("share_count")}


def recent_videos():
    d = _call("/v2/video/list/?fields=id,create_time,view_count,like_count,comment_count,share_count,share_url",
              {"max_count": 20})
    return d.get("videos", [])
