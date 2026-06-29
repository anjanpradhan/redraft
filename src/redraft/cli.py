"""CLI entry: read text on stdin, --mode fix|improve, print JSON result (or {"error"})."""

from __future__ import annotations

import argparse
import json
import sys

from .base import ReviewError
from .config import load_config
from .engine import review


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="redraft", description="Fix/improve text.")
    parser.add_argument("--mode", choices=["fix", "improve"], required=True)
    parser.add_argument("--input", help="read text from this file instead of stdin")
    parser.add_argument("--app", help="frontmost app bundle id (selects a per-app provider profile)")
    args = parser.parse_args(argv)

    try:
        if args.input:
            with open(args.input, encoding="utf-8") as f:
                text = f.read()
        else:
            text = sys.stdin.read()
    except (OSError, UnicodeDecodeError) as e:
        print(json.dumps({"error": f"cannot read input: {e}"}))
        return 1
    if not text.strip():
        print(json.dumps({"error": "empty input"}))
        return 1

    try:
        result = review(text, args.mode, load_config(), args.app)
    except ReviewError as e:
        print(json.dumps(e.to_dict()))
        return 1
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        return 1

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
