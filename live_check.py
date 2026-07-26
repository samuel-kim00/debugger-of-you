#!/usr/bin/env python3
"""Stage 2: check a new diff against the cached profile (fast, live).

Loads only developer_profile.json + the new diff, never the full history, so
this responds in seconds during the demo.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import ollama_client
import prompts


def check_diff(diff: str, profile_path: str = "developer_profile.json",
               model: str = ollama_client.DEFAULT_MODEL, num_ctx: int = 16384) -> dict:
    profile_json = Path(profile_path).read_text()
    return ollama_client.generate_json(
        prompts.live_prompt(profile_json, diff),
        prompts.LIVE_SCHEMA,
        model=model,
        num_ctx=num_ctx,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", help="Path to a diff file. Omit to read stdin.")
    ap.add_argument("--profile", default="developer_profile.json")
    ap.add_argument("--model", default=ollama_client.DEFAULT_MODEL)
    args = ap.parse_args()

    diff = Path(args.diff).read_text() if args.diff else sys.stdin.read()
    if not diff.strip():
        sys.exit("no diff provided")

    t0 = time.time()
    result = check_diff(diff, args.profile, args.model)
    dt = time.time() - t0

    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\n[{len(result.get('matches', []))} matches in {dt:.1f}s]", file=sys.stderr)


if __name__ == "__main__":
    main()
