"""YouTube Shorts upload via YouTube Data API v3 (resumable upload, plain HTTP).

Secrets: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN (from scripts/auth_youtube.py).
The Google OAuth app must be set to "In production" or refresh tokens die after 7 days.
"""
import json
import os

import requests

from .. import common as C

_cache = {}


def access_token():
    if "t" in _cache:
        return _cache["t"]
    r = requests.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "client_id": C.secret("YT_CLIENT_ID"), "client_secret": C.secret("YT_CLIENT_SECRET"),
        "refresh_token": C.secret("YT_REFRESH_TOKEN"), "grant_type": "refresh_token"})
    if r.status_code != 200:
        raise C.PostError(f"YouTube auth failed: {r.text[:300]} (re-run scripts/auth_youtube.py)")
    _cache["t"] = r.json()["access_token"]
    return _cache["t"]


def _err(r, what):
    try:
        e = r.json().get("error", {})
        msg = e.get("message") or r.text[:300]
        reason = (e.get("errors") or [{}])[0].get("reason", "")
    except ValueError:
        msg, reason = r.text[:300], ""
    raise C.PostError(f"YouTube {what}: {msg} {reason}".strip())


def post(item, mp4, video_url=None):
    title = item.get("yt_title") or item["caption"][:90]
    if "#shorts" not in title.lower():
        title = (title[:88] + " #Shorts").strip()
    tags = item.get("hashtags", [])
    desc = (item.get("yt_description", "") + "\n\n" + " ".join("#" + t for t in tags)).strip()
    meta = {
        "snippet": {"title": title[:100], "description": desc[:4900], "tags": tags[:15], "categoryId": "24"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True},
    }
    size = os.path.getsize(mp4)
    h = {"Authorization": f"Bearer {access_token()}"}
    r = requests.post("https://www.googleapis.com/upload/youtube/v3/videos", timeout=60,
                      params={"uploadType": "resumable", "part": "snippet,status"},
                      headers={**h, "Content-Type": "application/json; charset=UTF-8",
                               "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
                      data=json.dumps(meta))
    if r.status_code != 200:
        _err(r, "start upload")
    loc = r.headers["Location"]
    with open(mp4, "rb") as f:
        r = requests.put(loc, data=f, timeout=1800, headers={**h, "Content-Type": "video/mp4", "Content-Length": str(size)})
    if r.status_code not in (200, 201):
        _err(r, "upload")
    v = r.json()
    privacy = v.get("status", {}).get("privacyStatus")
    res = {"remote_id": v["id"], "url": f"https://youtube.com/shorts/{v['id']}"}
    if privacy and privacy != "public":
        res["warning"] = f"YouTube set this video to {privacy}. Your API project may need the YouTube audit."
    return res


def metrics(remote_id):
    r = requests.get("https://www.googleapis.com/youtube/v3/videos", timeout=30,
                     params={"part": "statistics,status", "id": remote_id},
                     headers={"Authorization": f"Bearer {access_token()}"})
    if r.status_code != 200:
        _err(r, "stats")
    items = r.json().get("items", [])
    if not items:
        return {}
    s = items[0].get("statistics", {})
    return {"views": int(s.get("viewCount", 0)), "likes": int(s.get("likeCount", 0)),
            "comments": int(s.get("commentCount", 0)), "privacy": items[0].get("status", {}).get("privacyStatus")}
