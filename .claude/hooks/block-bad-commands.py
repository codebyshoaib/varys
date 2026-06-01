#!/usr/bin/env python3
"""PreToolUse/Bash guard. Blocks ONLY specific dangerous patterns. Silent on success."""
import json, re, sys

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # never block on malformed input
    cmd = (data.get("tool_input", {}) or {}).get("command", "") or ""

    blocks = [
        (r"\brm\s+-rf\s+(~|/home/oye|\$HOME)(/\s|/?$|\s|$)",
         "Blocked: rm -rf on home root. Target a specific subdirectory."),
        (r"\brm\s+-rf\s+([^|&;]*/)?vault(/\s|/?$|\s|$)",
         "Blocked: rm -rf on the vault. The vault is Kamil's memory — delete specific files only."),
        (r"git\s+push\b[^|&;]*--force[^|&;]*\b(master|main)\b|git\s+push\b[^|&;]*\bmaster\b[^|&;]*--force",
         "Blocked: force-push to master/main. Use a branch + PR."),
        (r"git\s+add\b[^|&;]*(\.slack|\.env)\b",
         "Blocked: staging a secrets file (.slack/.env). Stage explicit non-secret paths."),
        (r"git\s+add\s+(-A|--all|\.)(\s|$)",
         "Blocked: `git add -A`/`git add .` can stage secrets. Stage explicit paths instead."),
        (r"\b(pkill|kill(all)?)\b[^|&;]*kamil-slack-listener",
         "Blocked: killing the Slack listener daemon. Stop it deliberately if truly intended."),
    ]
    for pattern, msg in blocks:
        if re.search(pattern, cmd):
            print(msg, file=sys.stderr)
            sys.exit(2)
    sys.exit(0)

if __name__ == "__main__":
    main()
