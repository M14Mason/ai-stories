"""Instagram Reels via the Instagram API with Instagram Login (graph.instagram.com).

Own account, app in Development mode, account added as Instagram Tester.
Secrets: IG_ACCESS_TOKEN (long-lived, 60 days, auto-refreshed), IG_USER_ID (optional, looked up).
"""
import os
import time

import requests

from .. import common as C
from .. import gh

GRAPH = "https://graph.instagram.com"


def _tok():
    return C.secret("IG_ACCESS_TOKEN")


def _ver():
    return C.settings().get("instagram_api_version", "v23.0")


def _check(r, what):
    try:
        j = r.json()
    except ValueError:
        j = {}
    if r.status_code >= 400 or "error" in j:
        msg = j.get("error", {}).get("message") or r.text[:300]
        raise C.PostError(f"Instagram {what}: {msg}")
    return j


def user_id():
    uid = os.environ.get("IG_USER_ID", "").strip()
    if uid:
        return uid
    j = _check(requests.get(f"{GRAPH}/{_ver()}/me", params={"fields": "user_id,username", "access_token": _tok()}, timeout=30), "me")
    return j.get("user_id") or j["id"]


def _wait(container, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = _check(requests.get(f"{GRAPH}/{_ver()}/{container}", params={"fields": "status_code,status", "access_token": _tok()}, timeout=30), "status")
        code = j.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise C.PostError(f"Instagram processing {code}: {j.get('status', '')}")
        time.sleep(10)
    raise C.PostError("Instagram processing timed out")


def _container_resumable(uid, caption, mp4):
    j = _check(requests.post(f"{GRAPH}/{_ver()}/{uid}/media", timeout=60, data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption,
        "share_to_feed": "true", "access_token": _tok()}), "create container")
    cid, uri = j["id"], j.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{_ver()}/{j['id']}"
    size = os.path.getsize(mp4)
    with open(mp4, "rb") as f:
        r = requests.post(uri, data=f, timeout=900, headers={
            "Authorization": f"OAuth {_tok()}", "offset": "0", "file_size": str(size)})
    _check(r, "upload")
    return cid


def _container_url(uid, caption, url):
    j = _check(requests.post(f"{GRAPH}/{_ver()}/{uid}/media", timeout=60, data={
        "media_type": "REELS", "video_url": url, "caption": caption,
        "share_to_feed": "true", "access_token": _tok()}), "create container (url)")
    return j["id"]


def post(item, mp4, video_url=None):
    uid = user_id()
    caption = item["caption"]
    try:
        cid = _container_resumable(uid, caption, mp4)
    except C.PostError as e:
        if not video_url:
            raise
        C.log(f"  resumable upload failed ({e}); trying video_url")
        cid = _container_url(uid, caption, video_url)
    _wait(cid)
    j = _check(requests.post(f"{GRAPH}/{_ver()}/{uid}/media_publish", timeout=60,
                             data={"creation_id": cid, "access_token": _tok()}), "publish")
    mid = j["id"]
    link = ""
    try:
        link = _check(requests.get(f"{GRAPH}/{_ver()}/{mid}", params={"fields": "permalink", "access_token": _tok()}, timeout=30), "permalink").get("permalink", "")
    except C.PostError:
        pass
    return {"remote_id": mid, "url": link}


def quota():
    uid = user_id()
    j = _check(requests.get(f"{GRAPH}/{_ver()}/{uid}/content_publishing_limit",
                            params={"fields": "quota_usage,config", "access_token": _tok()}, timeout=30), "quota")
    return j.get("data", [{}])[0]


def metrics(remote_id):
    j = _check(requests.get(f"{GRAPH}/{_ver()}/{remote_id}/insights", timeout=30, params={
        "metric": "views,reach,likes,comments,shares,saved", "access_token": _tok()}), "insights")
    out = {}
    for m in j.get("data", []):
        vals = m.get("values") or [{}]
        out[m["name"]] = vals[0].get("value", m.get("total_value", {}).get("value"))
    return out


def refresh(force=False):
    """Long-lived tokens last 60 days. Refresh weekly and store the new one."""
    j = _check(requests.get(f"{GRAPH}/refresh_access_token", timeout=30,
                            params={"grant_type": "ig_refresh_token", "access_token": _tok()}), "refresh")
    new = j.get("access_token")
    if new and new != _tok():
        gh.set_secret("IG_ACCESS_TOKEN", new)
    return j.get("expires_in")
