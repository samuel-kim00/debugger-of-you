#!/usr/bin/env python3
"""Stage 1: corpus.txt -> developer_profile.json (one Gemma pass, cached).

Slow and one-shot by design: it reads the whole history in a single context.
Runs offline against a local Ollama server. The result is cached to disk so the
live-check stage never reloads the full history.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import ollama_client
import prepare_history
import prompts


def _norm(s: str) -> str:
    return "".join(str(s).split())


def _commit_date(repo: Path, sha: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%ad",
                        "--date=short", sha], capture_output=True, text=True)
    return r.stdout.strip()


def verify(profile: dict, repo: Path) -> dict:
    """Two hard guarantees that turn the 4B model's imperfect recall into
    something trustworthy:
      1. grounding — every cited line must actually exist in that commit;
      2. recurrence — a pattern must span 2+ DISTINCT commits on 2+ DISTINCT
         dates, so three lines dumped in one commit (e.g. the initial commit)
         never masquerade as a "mistake you keep making over time".
    """
    diff_cache: dict[str, str] = {}
    kept_patterns = []
    dropped_occ = 0
    dropped_patterns = []
    for pat in profile.get("patterns", []):
        kept = []
        for occ in pat.get("occurrences", []):
            sha, line = occ.get("sha", ""), occ.get("line", "")
            if not sha or not line:
                dropped_occ += 1
                continue
            if sha not in diff_cache:
                try:
                    diff_cache[sha] = prepare_history.filtered_diff(repo, sha)
                except SystemExit:
                    diff_cache[sha] = ""
            if _norm(line) and _norm(line) in _norm(diff_cache[sha]):
                kept.append(occ)
            else:
                dropped_occ += 1
        pat["occurrences"] = kept
        commits = {o.get("sha", "")[:10] for o in kept}
        dates = {_commit_date(repo, s) for s in commits} - {""}
        if len(commits) >= 2 and len(dates) >= 2:
            kept_patterns.append(pat)
        else:
            dropped_patterns.append(f"{pat.get('name','?')} ({len(commits)} commit/{len(dates)} date)")
    profile["patterns"] = kept_patterns
    profile["_verification"] = {"dropped_occurrences": dropped_occ,
                                "verified_patterns": len(kept_patterns),
                                "dropped_patterns": dropped_patterns}
    return profile


def _default_repo() -> str:
    m = Path("manifest.json")
    if m.exists():
        return json.loads(m.read_text()).get("repo", "")
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus.txt")
    ap.add_argument("--out", default="developer_profile.json")
    ap.add_argument("--model", default=ollama_client.DEFAULT_MODEL)
    ap.add_argument("--num-ctx", type=int, default=65536)
    ap.add_argument("--repo", default=_default_repo(),
                    help="Repo to verify cited lines against (defaults to manifest.json).")
    ap.add_argument("--verify-only", action="store_true",
                    help="Skip the model; re-verify an existing profile with current rules.")
    args = ap.parse_args()

    if args.verify_only:
        profile = json.loads(Path(args.out).read_text())
        raw = len(profile.get("patterns", []))
        profile = verify(profile, Path(args.repo).expanduser())
        v = profile["_verification"]
        Path(args.out).write_text(json.dumps(profile, indent=2, ensure_ascii=False))
        print(f"re-verified: {raw} -> {v['verified_patterns']} patterns; "
              f"dropped: {v['dropped_patterns']}")
        for p in profile["patterns"]:
            print(f"  [{p.get('category','?')}/{p.get('severity','?')}] {p['name']} "
                  f"({len({o.get('sha') for o in p['occurrences']})} commits)")
        return

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

    raw_pat = len(profile.get("patterns", []))
    if args.repo:
        profile = verify(profile, Path(args.repo).expanduser())
        v = profile.get("_verification", {})
        print(f"verified against {args.repo}: dropped {v.get('dropped_occurrences',0)} "
              f"ungrounded lines, {raw_pat} -> {v.get('verified_patterns',0)} patterns")
    else:
        print("WARNING: no --repo, skipping verification")

    Path(args.out).write_text(json.dumps(profile, indent=2, ensure_ascii=False))
    n_pat = len(profile.get("patterns", []))
    print(f"done in {dt:.0f}s: {n_pat} verified patterns -> {args.out}")
    for p in profile.get("patterns", []):
        print(f"  [{p.get('category','?')}/{p.get('severity','?')}] {p['name']} "
              f"({len(p.get('occurrences', []))} verified commits)")


if __name__ == "__main__":
    main()
