#!/usr/bin/env python3
"""PreToolUse/Write|Edit guard. Blocks CLAUDE.md >150 lines; warns on secret writes."""
import json, os, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
try:
    import kamil_log as _k
except Exception:
    _k = None

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    ti = data.get("tool_input", {}) or {}
    path = ti.get("file_path", "") or ""

    base = os.path.basename(path)
    if base in (".slack", ".env"):
        print(f"WARNING: writing {base} — verify you are not clobbering live credentials.", file=sys.stderr)
        sys.exit(0)

    if base == "CLAUDE.md":
        content = ti.get("content")
        if content is None:
            try:
                with open(path) as f:
                    existing = sum(1 for _ in f)
            except Exception:
                existing = 0
            new_str = ti.get("new_string", "") or ""
            old_str = ti.get("old_string", "") or ""
            delta = new_str.count("\n") - old_str.count("\n")
            projected = existing + delta
        else:
            projected = content.count("\n") + 1
        if projected > 150:
            print(f"ERROR: CLAUDE.md would be ~{projected} lines (limit 150). Move detail to .claude/rules/ or vault/memory/.", file=sys.stderr)
            if _k: _k.klog_policy_block("guard-file-writes", rule="claude_md_size", reason=f"~{projected} lines", path=path)
            sys.exit(2)
    sys.exit(0)

if __name__ == "__main__":
    main()
