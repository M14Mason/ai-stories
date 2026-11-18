"""Run ONCE on your Mac to get a TikTok refresh token. Standard library only.

1. developers.tiktok.com > Manage apps > Connect an app. Add products "Login Kit" and
   "Content Posting API". Scopes: user.info.basic, video.upload, video.list.
   (video.publish only if you later pass TikTok's audit and switch to direct mode.)
2. Login Kit > Redirect URI:  https://<your-github-username>.github.io/<repo>/callback.html
3. Sandbox tab: add your own TikTok account as a target user.
4. Run:  python3 scripts/auth_tiktok.py   and follow the prompts.
5. Save the printed values as GitHub secrets.
"""
import json
import secrets
import urllib.parse
import urllib.request
import webbrowser

SCOPES = "user.info.basic,video.upload,video.list"


def main():
    key = input("Client key: ").strip()
    sec = input("Client secret: ").strip()
    redirect = input("Redirect URI (exactly as registered): ").strip()
    state = secrets.token_urlsafe(12)
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": key, "scope": SCOPES, "response_type": "code", "redirect_uri": redirect, "state": state})
    print("Opening TikTok sign-in. If it does not open, paste this URL:\n" + url)
    webbrowser.open(url)
    code = input("\nAfter approving, the callback page shows a code. Paste it here: ").strip()
    code = urllib.parse.unquote(code)
    body = urllib.parse.urlencode({"client_key": key, "client_secret": sec, "code": code,
                                   "grant_type": "authorization_code", "redirect_uri": redirect}).encode()
    req = urllib.request.Request("https://open.tiktokapis.com/v2/oauth/token/", data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    tok = json.load(urllib.request.urlopen(req))
    if "refresh_token" not in tok:
        raise SystemExit(f"Failed: {tok}")
    print("\nAdd these as GitHub secrets:")
    print("TT_CLIENT_KEY =", key)
    print("TT_CLIENT_SECRET =", sec)
    print("TT_REFRESH_TOKEN =", tok["refresh_token"])
    print("Scopes granted:", tok.get("scope"))


if __name__ == "__main__":
    main()
