"""GitHub API: release hosting for videos and secret write-back for refreshed tokens."""
import base64
import os

import requests

from . import common as C

API = "https://api.github.com"


def repo():
    return C.secret("GITHUB_REPOSITORY")


def _h(token=None):
    return {"Authorization": f"Bearer {token or C.secret('GITHUB_TOKEN')}",
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def release(tag):
    r = requests.get(f"{API}/repos/{repo()}/releases/tags/{tag}", headers=_h(), timeout=30)
    if r.status_code == 200:
        return r.json()
    r = requests.post(f"{API}/repos/{repo()}/releases", headers=_h(), timeout=30,
                      json={"tag_name": tag, "name": tag, "body": "Auto-built episodes", "prerelease": True})
    r.raise_for_status()
    return r.json()


def upload(tag, file_path, content_type):
    """Upload a file to a release (replacing a same-named asset). Returns its public download URL."""
    rel = release(tag)
    name = os.path.basename(file_path)
    for a in rel.get("assets", []):
        if a["name"] == name:
            requests.delete(f"{API}/repos/{repo()}/releases/assets/{a['id']}", headers=_h(), timeout=30).raise_for_status()
    url = rel["upload_url"].split("{")[0]
    with open(file_path, "rb") as f:
        r = requests.post(url, params={"name": name}, data=f, timeout=600,
                          headers={**_h(), "Content-Type": content_type})
    r.raise_for_status()
    return r.json()["browser_download_url"]


def set_secret(name, value):
    """Store a refreshed token back into the repo's Actions secrets (needs GH_PAT with Secrets: write)."""
    from nacl import encoding, public
    pat = os.environ.get("GH_PAT", "").strip()
    if not pat:
        C.log(f"  GH_PAT not set: cannot save refreshed {name}; it will expire")
        return False
    h = _h(pat)
    k = requests.get(f"{API}/repos/{repo()}/actions/secrets/public-key", headers=h, timeout=30)
    k.raise_for_status()
    k = k.json()
    box = public.SealedBox(public.PublicKey(k["key"].encode(), encoding.Base64Encoder()))
    enc = base64.b64encode(box.encrypt(value.encode())).decode()
    r = requests.put(f"{API}/repos/{repo()}/actions/secrets/{name}", headers=h, timeout=30,
                     json={"encrypted_value": enc, "key_id": k["key_id"]})
    r.raise_for_status()
    os.environ[name] = value
    C.log(f"  saved refreshed secret {name}")
    return True
