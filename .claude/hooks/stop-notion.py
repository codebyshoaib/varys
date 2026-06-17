#!/usr/bin/env python3
"""
stop-notion hook — stub.

Notion Work Log writes are no longer done at session stop.
Session summaries go to vault/logs/ via other hooks (session-logger.py, stop.py).
This file is kept as a hook stub because the hook system still references it.
Returns 0 immediately without any Notion HTTP calls.
"""
import sys


def main() -> int:
    # Session summary goes to vault/logs/ via session-logger.py.
    # No Notion write needed here.
    print("[stop-notion] skipped (Notion work-log write removed)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
