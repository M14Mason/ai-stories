"""Run ONCE on your Mac to get a YouTube refresh token. Standard library only.

1. Google Cloud Console: create a project, enable "YouTube Data API v3".
2. OAuth consent screen: External, add your Google account as a test user, then click
   PUBLISH APP ("In production"). Testing-mode refresh tokens expire after 7 days.
3. Credentials > Create OAuth client ID > "Desktop app". Copy the client ID and secret.
4. Run:  python3 scripts/auth_youtube.py
   Sign in with the account that owns the channel. Google will warn the app is unverified:
   click Advanced > Go to app (it is your own app).
5. Save the three printed values as GitHub secrets.
"""
import http.server
import json
import secrets
import urllib.parse
import urllib.request
import webbrowser

SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
PORT = 8765


def main():
    cid = input("Client ID: ").strip()
    csec = input("Client secret: ").strip()
    state = secrets.token_urlsafe(16)
    redirect = f"http://127.0.0.1:{PORT}/"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": SCOPES,
        "access_type": "offline", "prompt": "consent", "state": state})
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200); self.end_headers()
            self.wfile.write(b"Done. You can close this tab and go back to the terminal.")

        def log_message(self, *a):
            pass

    print("Opening your browser. If it does not open, paste this URL:\n" + url)
    webbrowser.open(url)
    srv = http.server.HTTPServer(("127.0.0.1", PORT), H)
    while "code" not in got and "error" not in got:
        srv.handle_request()
    if got.get("state") != state or "code" not in got:
        raise SystemExit(f"Sign-in failed: {got}")
    body = urllib.parse.urlencode({"code": got["code"], "client_id": cid, "client_secret": csec,
                                   "redirect_uri": redirect, "grant_type": "authorization_code"}).encode()
    tok = json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", data=body))
    if "refresh_token" not in tok:
        raise SystemExit(f"No refresh token returned: {tok}")
    print("\nAdd these as GitHub secrets (Settings > Secrets and variables > Actions):")
    print("YT_CLIENT_ID =", cid)
    print("YT_CLIENT_SECRET =", csec)
    print("YT_REFRESH_TOKEN =", tok["refresh_token"])


if __name__ == "__main__":
    main()
