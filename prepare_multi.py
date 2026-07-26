#!/usr/bin/env python3
"""Stage 0 (multi-repo): combine ONE developer's history across several repos.

A single project shows that project's patterns. To profile a *person* you need
several of their projects — a habit that shows up in the trading bot AND the
photo editor is the person, not the project. This:

  - takes several repos + an author filter (only that developer's commits),
  - extracts source diffs per commit, tags each block with its repo,
  - stratified-samples PER REPO into a shared token budget,
  - writes one corpus.txt + a manifest that records which repo each commit came
    from (so later stages can verify against the right repo).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import prepare_history as ph


def authored_commits(repo: Path, author: str) -> list[tuple[str, str, str]]:
    out = ph.run(["git", "log", "--reverse", "--date=short", "--author", author,
                  "--pretty=format:%H\t%ad\t%s"], repo)
    rows = []
    for line in out.splitlines():
        p = line.split("\t", 2)
        if len(p) == 3:
            rows.append((p[0], p[1], p[2]))
    return rows


def stratified(items: list[dict], budget: int) -> list[dict]:
    """Keep all if they fit; else thin the middle by a widening stride."""
    total = sum(c["tokens"] for c in items)
    if total <= budget:
        return items
    n = len(items)
    for stride in range(2, n + 1):
        idx = sorted(set([0, n - 1] + list(range(0, n, stride))))
        kept = [items[i] for i in idx]
        if sum(c["tokens"] for c in kept) <= budget:
            return kept
    return items[-1:]


def build(repos: list[tuple[str, Path]], author: str, budget: int, cap: int):
    per_budget = budget // max(1, len(repos))
    blocks, kept_meta = [], []
    per_repo_counts = {}
    for name, path in repos:
        rows = authored_commits(path, author)
        commits = []
        for sha, date, subject in rows:
            diff = ph.cap_commit(ph.filtered_diff(path, sha), cap)
            if not diff:
                continue
            commits.append({"repo": name, "path": str(path), "sha": sha, "date": date,
                            "subject": subject, "diff": diff, "tokens": ph.est_tokens(diff)})
        kept = stratified(commits, per_budget)
        per_repo_counts[name] = {"total": len(rows), "with_source": len(commits), "kept": len(kept)}
        for c in kept:
            blocks.append(f"===== [{c['repo']}] COMMIT {c['sha'][:10]} | {c['date']} | {c['subject']} =====\n{c['diff']}")
            kept_meta.append({"sha": c["sha"][:10], "repo": c["repo"], "path": c["path"],
                              "date": c["date"], "subject": c["subject"], "tokens": c["tokens"]})

    corpus = "\n\n".join(blocks)
    manifest = {
        "repos": {name: str(path) for name, path in repos},
        "author": author,
        "budget_tokens": budget,
        "per_commit_token_cap": cap,
        "corpus_tokens_est": ph.est_tokens(corpus),
        "commits_kept": len(kept_meta),
        "commits_total": sum(v["total"] for v in per_repo_counts.values()),
        "per_repo": per_repo_counts,
        "kept": kept_meta,
    }
    return corpus, manifest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", required=True,
                    help="Comma-separated name:path pairs, e.g. 'trading-bot:~/Trading bot,photo:~/photo-editor'")
    ap.add_argument("--author", required=True, help="Author substring (email or name) to keep.")
    ap.add_argument("--budget", type=int, default=52000)
    ap.add_argument("--per-commit-cap", type=int, default=2400)
    ap.add_argument("--out-dir", default=".")
    args = ap.parse_args()

    repos = []
    for pair in args.repos.split(","):
        name, _, path = pair.partition(":")
        repos.append((name.strip(), Path(path.strip()).expanduser().resolve()))
    for name, path in repos:
        if not (path / ".git").exists():
            raise SystemExit(f"not a git repo: {path}")

    corpus, manifest = build(repos, args.author, args.budget, args.per_commit_cap)
    out = Path(args.out_dir).expanduser().resolve()
    (out / "corpus.txt").write_text(corpus)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"repos: {len(repos)} | commits kept: {manifest['commits_kept']} "
          f"| ~{manifest['corpus_tokens_est']} tokens")
    for name, c in manifest["per_repo"].items():
        print(f"  {name:16} {c['kept']:3} kept / {c['with_source']} source / {c['total']} authored")


if __name__ == "__main__":
    main()
