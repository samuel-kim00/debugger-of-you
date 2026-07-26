#!/usr/bin/env python3
"""Stage 1: corpus.txt -> developer_profile.json (one Gemma pass, cached).

Slow and one-shot by design: it reads the whole history in a single context.
Runs offline against a local Ollama server. The result is cached to disk so the
live-check stage never reloads the full history.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import ollama_client
import prompts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus.txt")
    ap.add_argument("--out", default="developer_profile.json")
    ap.add_argument("--model", default=ollama_client.DEFAULT_MODEL)
    ap.add_argument("--num-ctx", type=int, default=65536)
    args = ap.parse_args()

    corpus = Path(args.corpus).read_text()
    approx_tokens = len(corpus) // 4
    print(f"corpus: ~{approx_tokens} tokens -> model {args.model} @ num_ctx {args.num_ctx}")
    print("building profile (this is the slow one-shot pass)...")

    t0 = time.time()
    profile = ollama_client.generate_json(
        prompts.profile_prompt(corpus),
        prompts.PROFILE_SCHEMA,
        model=args.model,
        num_ctx=args.num_ctx,
    )
    dt = time.time() - t0

    Path(args.out).write_text(json.dumps(profile, indent=2, ensure_ascii=False))
    n_pat = len(profile.get("patterns", []))
    print(f"done in {dt:.0f}s: {n_pat} patterns -> {args.out}")
    for p in profile.get("patterns", []):
        print(f"  [{p.get('category','?')}/{p.get('severity','?')}] {p['name']} "
              f"({len(p.get('occurrences', []))} commits)")


if __name__ == "__main__":
    main()
