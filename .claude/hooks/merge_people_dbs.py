#!/usr/bin/env python3
"""
merge-people-dbs.py — One-time migration: Team People / focus → People Intelligence.

Usage:
  python3 merge-people-dbs.py --dry-run   # print match report, no writes
  python3 merge-people-dbs.py --write     # requires prior dry-run approval
"""
import sys, os, json, argparse, urllib.request
sys.path.insert(0, os.path.dirname(__file__))

try:
    from Levenshtein import distance as lev_distance
except ImportError:
    def lev_distance(a, b):
        m, n = len(a), len(b)
        dp = list(range(n + 1))
        for i in range(1, m + 1):
            prev = dp[:]
            dp[0] = i
            for j in range(1, n + 1):
                dp[j] = prev[j - 1] if a[i-1] == b[j-1] else 1 + min(prev[j], dp[j-1], prev[j-1])
        return dp[n]

SOURCE_DB_ID = "bbf6ade203e543f39f4c64a2f05fe29e"
TARGET_DB_ID = "c976d58ea4e34b0585f245529cdc4528"
NOTION_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

def _notion_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

def _get_api_key() -> str:
    key = os.environ.get("NOTION_API_KEY")
    if not key:
        # check ~/.claude/hooks/.notion (same source as other hooks)
        notion_cfg = os.path.expanduser("~/.claude/hooks/.notion")
        if os.path.exists(notion_cfg):
            for line in open(notion_cfg):
                line = line.strip()
                if line.startswith("NOTION_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not key:
        raise RuntimeError("NOTION_API_KEY not set. Add to env or ~/.claude/hooks/.notion")
    return key

def _fetch_db_pages(db_id: str) -> list:
    from kamil_notion import notion_request
    api_key = _get_api_key()
    results, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{NOTION_BASE}/databases/{db_id}/query",
            data=data,
            headers=_notion_headers(api_key),
            method="POST",
        )
        _, body_bytes = notion_request(req)
        resp = json.loads(body_bytes)
        results.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return results

def _page_to_dict(page: dict) -> dict:
    props = page.get("properties", {})
    def text(p):
        items = p.get("rich_text") or p.get("title") or []
        return "".join(i["plain_text"] for i in items)
    return {
        "notion_page_id": page["id"],
        "name": text(props.get("Name", {})),
        "slack_id": text(props.get("Slack ID", {})),
        "role": text(props.get("Role", {})),
        "current_focus": text(props.get("Current Focus", props.get("Focus", {}))),
    }

def match_people(source: list, target: list) -> list:
    """Match source records against target by name. Returns list of match dicts."""
    results = []
    for s in source:
        best_target, best_dist = None, 999
        for t in target:
            d = lev_distance(s["name"].lower(), t["name"].lower())
            if d < best_dist:
                best_dist, best_target = d, t
        if best_dist == 0:
            results.append({"source": s, "target": best_target, "match_type": "exact", "distance": 0})
        elif best_dist <= 2:
            results.append({"source": s, "target": best_target, "match_type": "fuzzy", "distance": best_dist})
        else:
            results.append({"source": s, "target": None, "match_type": "new", "distance": best_dist})
    return results

def print_report(matches: list):
    exact  = [m for m in matches if m["match_type"] == "exact"]
    fuzzy  = [m for m in matches if m["match_type"] == "fuzzy"]
    new    = [m for m in matches if m["match_type"] == "new"]

    print(f"\n## Merge Dry-Run Report\n")
    print(f"**Exact matches ({len(exact)})** — will merge fields (role, current focus):\n")
    print("| Source Name | Target Name |")
    print("|---|---|")
    for m in exact:
        print(f"| {m['source']['name']} | {m['target']['name']} |")

    print(f"\n**Fuzzy matches ({len(fuzzy)})** — REVIEW BEFORE WRITING:\n")
    print("| Source Name | Target Name | Edit Distance |")
    print("|---|---|---|")
    for m in fuzzy:
        print(f"| {m['source']['name']} | {m['target']['name']} | {m['distance']} |")

    print(f"\n**New records ({len(new)})** — will be created in People Intelligence:\n")
    print("| Name |")
    print("|---|")
    for m in new:
        print(f"| {m['source']['name']} |")

    print(f"\n---\nReview fuzzy matches carefully. Run with --write only after approval.")

def do_write(matches: list):
    from kamil_notion import notion_request
    api_key = _get_api_key()

    def _patch(page_id, updates):
        data = json.dumps({"properties": updates}).encode()
        req = urllib.request.Request(
            f"{NOTION_BASE}/pages/{page_id}",
            data=data,
            headers=_notion_headers(api_key),
            method="PATCH",
        )
        notion_request(req)

    def _create(props):
        data = json.dumps({"parent": {"database_id": TARGET_DB_ID}, "properties": props}).encode()
        req = urllib.request.Request(
            f"{NOTION_BASE}/pages",
            data=data,
            headers=_notion_headers(api_key),
            method="POST",
        )
        notion_request(req)

    for m in matches:
        s = m["source"]
        if m["match_type"] in ("exact", "fuzzy"):
            t = m["target"]
            updates = {}
            if s.get("role") and not t.get("role"):
                updates["Role"] = {"rich_text": [{"text": {"content": s["role"]}}]}
            if s.get("current_focus") and not t.get("current_focus"):
                updates["Current Focus"] = {"rich_text": [{"text": {"content": s["current_focus"]}}]}
            if s.get("slack_id") and not t.get("slack_id"):
                updates["Slack ID"] = {"rich_text": [{"text": {"content": s["slack_id"]}}]}
            if updates:
                _patch(t["notion_page_id"], updates)
                print(f"  Updated: {t['name']}")
        elif m["match_type"] == "new":
            _create({
                "Name": {"title": [{"text": {"content": s["name"]}}]},
                "Slack ID": {"rich_text": [{"text": {"content": s.get("slack_id", "")}}]},
                "Role": {"rich_text": [{"text": {"content": s.get("role", "")}}]},
            })
            print(f"  Created: {s['name']}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not args.write:
        print("Pass --dry-run or --write", file=sys.stderr)
        sys.exit(1)

    print("Fetching source DB (Team People / focus)...")
    source_pages = _fetch_db_pages(SOURCE_DB_ID)
    source = [_page_to_dict(p) for p in source_pages]

    print("Fetching target DB (People Intelligence)...")
    target_pages = _fetch_db_pages(TARGET_DB_ID)
    target = [_page_to_dict(p) for p in target_pages]

    matches = match_people(source, target)

    if args.dry_run:
        print_report(matches)
    elif args.write:
        print("Writing...")
        do_write(matches)
        print("Done.")
