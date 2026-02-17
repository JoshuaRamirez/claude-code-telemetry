#!/usr/bin/env python3
"""SessionEnd hook - logs authoritative session close to database.

This is the only hook that sets EndedAt on the session.
Stop hooks no longer close sessions (to support /resume and multi-stop sessions).
"""

import json
import os
import sys

# Add hooks directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db_logger import log_event


def main():
    try:
        input_data = json.load(sys.stdin)
        result = log_event('SessionEnd', input_data)
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"systemMessage": f"DB hook error: {e}"}), file=sys.stdout)
    finally:
        sys.exit(0)


if __name__ == '__main__':
    main()
