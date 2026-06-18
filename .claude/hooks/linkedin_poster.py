#!/usr/bin/env python3
"""
linkedin_poster.py — Post text + image to LinkedIn on Shoaib's behalf.

Uses LinkedIn UGC Posts API with w_member_social scope.
Token valid 2 months — stored in ~/.claude/hooks/.linkedin
"""

import json
import sys
import urllib.request
import urllib.parse
from pathlib import Path
import sys as _sys, time as _time
_sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
try:
    import varys_log as _k
except Exception:
    _k = None

LINKEDIN_CFG = Path.home() / ".claude" / "hooks" / ".linkedin"
API_BASE     = "https://api.linkedin.com/v2"


def load_token() -> str:
    if LINKEDIN_CFG.exists():
        for line in LINKEDIN_CFG.read_text().splitlines():
            if line.startswith("LINKEDIN_ACCESS_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def get_person_urn(token: str) -> str:
    req = urllib.request.Request(
        f"{API_BASE}/userinfo",
        headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    return f"urn:li:person:{data['sub']}"


def normalize_image(image_path: str, target_w: int = 1080, target_h: int = 1350) -> str:
    """Fit image into target_w×target_h with background-color padding — no crop, no data loss."""
    from PIL import Image
    import tempfile
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    scale = min(target_w / w, target_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    bg_color = img.getpixel((0, 0))  # sample background from corner
    canvas = Image.new("RGB", (target_w, target_h), bg_color)
    canvas.paste(img, ((target_w - new_w) // 2, (target_h - new_h) // 2))
    out = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    canvas.save(out.name, "PNG")
    return out.name


def upload_image(token: str, person_urn: str, image_path: str) -> str:
    """Upload image and return asset URN."""
    image_path = normalize_image(image_path)
    headers = {
        "Authorization":  f"Bearer {token}",
        "Content-Type":   "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }
    reg_body = json.dumps({
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": person_urn,
            "serviceRelationships": [{
                "relationshipType": "OWNER",
                "identifier": "urn:li:userGeneratedContent"
            }]
        }
    }).encode()
    req = urllib.request.Request(
        f"{API_BASE}/assets?action=registerUpload",
        data=reg_body, headers=headers
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        reg = json.loads(r.read())

    upload_url = reg["value"]["uploadMechanism"][
        "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
    asset_urn  = reg["value"]["asset"]

    with open(image_path, "rb") as f:
        img_data = f.read()
    # LinkedIn's dms-uploads CDN requires an explicit image Content-Type on the PUT;
    # without it the upload is rejected with a 400 HTML page (not JSON).
    ext = Path(image_path).suffix.lower()
    content_type = {".png": "image/png", ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg", ".gif": "image/gif"}.get(ext, "image/png")
    ul_req = urllib.request.Request(upload_url, data=img_data,
                                    headers={"Authorization": f"Bearer {token}",
                                             "Content-Type": content_type},
                                    method="PUT")
    with urllib.request.urlopen(ul_req, timeout=60):
        pass
    return asset_urn


def post_text(token: str, text: str, visibility: str = "PUBLIC") -> dict:
    """Post text-only to LinkedIn."""
    person_urn = get_person_urn(token)
    headers = {
        "Authorization":  f"Bearer {token}",
        "Content-Type":   "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }
    payload = json.dumps({
        "author":         person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary":    {"text": text},
                "shareMediaCategory": "NONE"
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": visibility
        }
    }).encode()

    req = urllib.request.Request(
        f"{API_BASE}/ugcPosts",
        data=payload, headers=headers
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def post_image(token: str, text: str, image_path: str,
               visibility: str = "PUBLIC") -> dict:
    """Post text + image to LinkedIn."""
    person_urn = get_person_urn(token)
    asset_urn  = upload_image(token, person_urn, image_path)
    headers = {
        "Authorization":  f"Bearer {token}",
        "Content-Type":   "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }
    payload = json.dumps({
        "author":         person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary":    {"text": text},
                "shareMediaCategory": "IMAGE",
                "media": [{
                    "status":      "READY",
                    "description": {"text": ""},
                    "media":       asset_urn,
                    "title":       {"text": ""}
                }]
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": visibility
        }
    }).encode()
    req = urllib.request.Request(
        f"{API_BASE}/ugcPosts",
        data=payload, headers=headers
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def post_to_linkedin(text: str, image_path: str = None) -> str:
    """Main entry point. Returns post URL or error."""
    token = load_token()
    if not token:
        return "❌ No LinkedIn token — run OAuth flow first"
    try:
        if image_path and Path(image_path).exists():
            result = post_image(token, text, image_path)
        else:
            result = post_text(token, text)

        post_id = result.get("id", "")
        return f"✅ Posted to LinkedIn | ID: {post_id}"
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return f"❌ LinkedIn API error {e.code}: {body[:200]}"
    except Exception as e:
        return f"❌ Error: {e}"


if __name__ == "__main__":
    import argparse
    _t0 = _time.time()
    try:
        p = argparse.ArgumentParser()
        p.add_argument("--text",  required=True)
        p.add_argument("--image", default=None)
        args = p.parse_args()
        print(post_to_linkedin(args.text, args.image))
        if _k: _k.klog_cron("linkedin-poster", status="ok", duration_ms=(_time.time()-_t0)*1000)
    except Exception as _e:
        if _k: _k.klog_error("linkedin-poster-main", _e, component="linkedin-poster", severity="ERROR")
        raise
