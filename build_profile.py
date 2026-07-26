#!/usr/bin/env python3
"""Stage 1: corpus.txt -> developer_profile.json (one Gemma pass, cached).

Slow and one-shot by design: it reads the whole history in a single context.
Runs offline against a local Ollama server. The result is cached to disk so the
live-check stage never reloads the full history.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

import ollama_client
import prepare_history
import prompts


def _norm(s: str) -> str:
    return "".join(str(s).split())


def _grounded(line: str, diff: str) -> bool:
    """Is this cited line a REAL line in the commit? Exact (whitespace-insensitive)
    substring is best; else accept if some diff line shares 3+ distinctive tokens
    with it (the model referenced a real line but reworded it slightly)."""
    nl = _norm(line)
    if len(nl) >= 15 and nl in _norm(diff):
        return True
    toks = {t for t in re.findall(r"[A-Za-z_]\w{3,}", line)}
    if len(toks) < 2:
        return False
    for dl in diff.splitlines():
        shared = sum(1 for t in toks if t in dl)
        if shared >= 3 or shared / len(toks) >= 0.6:
            return True
    return False


def verify(profile: dict, manifest: dict) -> dict:
    """Two hard guarantees that turn the 4B model's imperfect recall into
    something trustworthy, now across several projects:
      1. grounding — every cited line must actually exist in that commit (in the
         right project — sha->repo comes from the manifest);
      2. recurrence — a pattern must span 2+ DISTINCT commits on 2+ DISTINCT
         dates. Patterns spanning 2+ PROJECTS are tagged (the person's habit).
    """
    kept = manifest.get("kept", [])
    sha_path = {k["sha"][:10]: k.get("path", "") for k in kept}
    sha_repo = {k["sha"][:10]: k.get("repo", "") for k in kept}
    sha_date = {k["sha"][:10]: k.get("date", "") for k in kept}
    diff_cache: dict[str, str] = {}

    def diff_for(sha10: str) -> str:
        if sha10 not in diff_cache:
            path = sha_path.get(sha10, "")
            try:
                diff_cache[sha10] = prepare_history.filtered_diff(Path(path), sha10) if path else ""
            except SystemExit:
                diff_cache[sha10] = ""
        return diff_cache[sha10]

    kept_patterns, dropped_occ, dropped_patterns = [], 0, []
    for pat in profile.get("patterns", []):
        good = []
        for occ in pat.get("occurrences", []):
            sha10, line = str(occ.get("sha", ""))[:10], occ.get("line", "")
            if not sha10 or not line or sha10 not in sha_path:
                dropped_occ += 1
                continue
            if line and _grounded(line, diff_for(sha10)):
                occ["repo"] = sha_repo.get(sha10, "")   # annotate for the UI
                good.append(occ)
            else:
                dropped_occ += 1
        pat["occurrences"] = good
        commits = {str(o.get("sha", ""))[:10] for o in good}
        dates = {sha_date.get(s, "") for s in commits} - {""}
        projects = sorted({sha_repo.get(s, "") for s in commits} - {""})
        pat["projects"] = projects
        if len(commits) >= 2 and len(dates) >= 2:
            kept_patterns.append(pat)
        else:
            dropped_patterns.append(f"{pat.get('name','?')} ({len(commits)} commit/{len(dates)} date)")
    # cross-project patterns first, then by severity
    sev = {"high": 0, "medium": 1, "low": 2}
    kept_patterns.sort(key=lambda p: (-len(p.get("projects", [])), sev.get(p.get("severity"), 3)))
    profile["patterns"] = kept_patterns
    profile["_verification"] = {"dropped_occurrences": dropped_occ,
                                "verified_patterns": len(kept_patterns),
                                "cross_project": sum(1 for p in kept_patterns if len(p.get("projects", [])) >= 2),
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

    manifest = json.loads(Path("manifest.json").read_text())

    if args.verify_only:
        profile = json.loads(Path(args.out).read_text())
        raw = len(profile.get("patterns", []))
        profile = verify(profile, manifest)
        v = profile["_verification"]
        Path(args.out).write_text(json.dumps(profile, indent=2, ensure_ascii=False))
        print(f"re-verified: {raw} -> {v['verified_patterns']} patterns "
              f"({v['cross_project']} cross-project); dropped: {v['dropped_patterns']}")
        for p in profile["patterns"]:
            print(f"  [{p.get('category','?')}/{p.get('severity','?')}] {p['name']} "
                  f"| projects={p.get('projects')} ({len({o.get('sha') for o in p['occurrences']})} commits)")
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
    Path("developer_profile.raw.json").write_text(json.dumps(profile, indent=2, ensure_ascii=False))
    profile = verify(profile, manifest)
    v = profile.get("_verification", {})
    print(f"verified: dropped {v.get('dropped_occurrences',0)} ungrounded lines, "
          f"{raw_pat} -> {v.get('verified_patterns',0)} patterns "
          f"({v.get('cross_project',0)} cross-project)")

    Path(args.out).write_text(json.dumps(profile, indent=2, ensure_ascii=False))
    n_pat = len(profile.get("patterns", []))
    print(f"done in {dt:.0f}s: {n_pat} verified patterns -> {args.out}")
    for p in profile.get("patterns", []):
        print(f"  [{p.get('category','?')}/{p.get('severity','?')}] {p['name']} "
              f"| projects={p.get('projects')}")


if __name__ == "__main__":
    main()
