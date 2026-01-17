#!/usr/bin/env python3
"""PreCompact hook - logs pre-compact events to database."""

import json
import sys
import os

# Add hooks directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db_logger import log_event


def main():
    try:
        input_data = json.load(sys.stdin)
        result = log_event('PreCompact', input_data)
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"systemMessage": f"DB hook error: {e}"}), file=sys.stdout)
    finally:
        sys.exit(0)


if __name__ == '__main__':
    main()
