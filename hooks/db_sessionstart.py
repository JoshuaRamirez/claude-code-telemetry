#!/usr/bin/env python3
"""SessionStart hook - logs session start events to database.

Runs a health check before logging. If prerequisites aren't met,
returns a systemMessage with actionable guidance instead of silently failing.
"""

import json
import sys
import os

# Add hooks directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from health_check import check_health
from db_logger import log_event


def main():
    try:
        input_data = json.load(sys.stdin)

        # Health check first -- give the user actionable feedback if something is wrong
        healthy, message = check_health()
        if not healthy:
            print(json.dumps({"systemMessage": message}))
            return

        result = log_event('SessionStart', input_data)
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"systemMessage": f"[claude-code-telemetry] Startup error: {e}"}), file=sys.stdout)
    finally:
        sys.exit(0)


if __name__ == '__main__':
    main()
