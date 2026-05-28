#!/usr/bin/env python3
"""
linkedin_oauth.py — Refresh LinkedIn access token via OAuth 2.0.

Run this when LinkedIn posts start failing with 400/401 errors.
Opens a local server on port 8080, prints the auth URL to visit,
captures the callback, exchanges code for token, saves to ~/.claude/hooks/.linkedin

Usage:
    python3 .claude/hooks/linkedin_oauth.py
"""

import json
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

LINKEDIN_CFG = Path.home() / ".claude" / "hooks" / ".linkedin"

def load_config():
    cfg = {}
    for line in LINKEDIN_CFG.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg

def save_token(token: str):
    cfg = load_config()
    cfg["LINKEDIN_ACCESS_TOKEN"] = token
    LINKEDIN_CFG.write_text("\n".join(f"{k}={v}" for k, v in cfg.items()) + "\n")
    print(f"✅ Token saved to {LINKEDIN_CFG}")

class OAuthHandler(BaseHTTPRequestHandler):
    token = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" not in params:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing code parameter")
            return

        code = params["code"][0]
        cfg  = load_config()

        # Exchange code for token
        data = urllib.parse.urlencode({
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  cfg["LINKEDIN_REDIRECT_URI"],
            "client_id":     cfg["LINKEDIN_CLIENT_ID"],
            "client_secret": cfg["LINKEDIN_CLIENT_SECRET"],
        }).encode()

        req = urllib.request.Request(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                result = json.loads(r.read())
            token = result.get("access_token", "")
            if token:
                save_token(token)
                OAuthHandler.token = token
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"<h1>LinkedIn token refreshed!</h1><p>You can close this tab. Kamil will now post automatically.</p>")
                print(f"\n✅ New token obtained and saved!")
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(f"Token exchange failed: {result}".encode())
                print(f"Token exchange failed: {result}")
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"Error: {e}".encode())
            print(f"Error: {e}")

    def log_message(self, *args):
        pass  # suppress server logs


def main():
    cfg = load_config()
    scope = "openid profile email w_member_social"
    auth_url = (
        "https://www.linkedin.com/oauth/v2/authorization?"
        + urllib.parse.urlencode({
            "response_type": "code",
            "client_id":     cfg["LINKEDIN_CLIENT_ID"],
            "redirect_uri":  cfg["LINKEDIN_REDIRECT_URI"],
            "scope":         scope,
        })
    )

    print("\n" + "="*60)
    print("LinkedIn OAuth Token Refresh")
    print("="*60)
    print(f"\nOpen this URL in your browser:\n\n{auth_url}\n")
    print("Waiting for callback on http://localhost:8080 ...")
    print("(Press Ctrl+C to cancel)\n")

    server = HTTPServer(("localhost", 8080), OAuthHandler)
    server.timeout = 120
    while OAuthHandler.token is None:
        server.handle_request()

    print("\nDone! LinkedIn posting will work again.")


if __name__ == "__main__":
    main()
