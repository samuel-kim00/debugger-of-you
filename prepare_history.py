#!/usr/bin/env python3
"""Stage 0: turn a repo's git history into one budget-fitting text corpus.

The whole thesis of "The Debugger of You" is feeding a developer's history to
Gemma 4 in ONE context, no per-diff chunking. On a 16GB M1 the usable context
is ~64K tokens, but a real repo's Python history is several times that. So we:

  1. walk commits oldest -> newest
  2. keep only source diffs (drop AI-generated docs, data, lockfiles, generated)
  3. cap any single commit so one giant refactor can't eat the whole budget
  4. if the total still overflows, stratified-sample ACROSS the timeline so the
     "same mistake across months" story survives (not just the recent tail)

Output is a single corpus.txt plus a manifest.json describing what made the cut.
Deterministic and model-free, so it runs while the model downloads.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

# ~4 chars per token is the rule of thumb the spec budgets against.
CHARS_PER_TOKEN = 4

# Paths whose diffs are noise for a *coding* autobiography or are generated.
# Matched as substrings against the file path in the diff header.
EXCLUDE_SUBSTRINGS = (
    "docs/superpowers/",   # AI-generated plans/specs, huge and not authored line-by-line
    "/__pycache__/",
    ".lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "/data/",
    "/logs/",
    "/models/",
    ".min.js",
    ".min.css",
)

# Only diffs for files with these extensions are kept.
INCLUDE_EXTENSIONS = (
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".rb", ".java", ".swift",
    ".sh", ".sql",
)


def est_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


@dataclass
class Commit:
    sha: str
    date: str          # ISO short date
    subject: str
    diff: str          # filtered, source-only diff body
    tokens: int


def run(cmd: list[str], cwd: Path) -> str:
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"git failed: {' '.join(cmd)}\n{res.stderr}")
    return res.stdout


def list_commits(repo: Path) -> list[tuple[str, str, str]]:
    """Oldest -> newest: (sha, iso-date, subject)."""
    out = run(
        ["git", "log", "--reverse", "--date=short",
         "--pretty=format:%H\t%ad\t%s"],
        repo,
    )
    rows = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            rows.append((parts[0], parts[1], parts[2]))
    return rows


def _file_included(header_path: str) -> bool:
    if any(sub in header_path for sub in EXCLUDE_SUBSTRINGS):
        return False
    return header_path.endswith(INCLUDE_EXTENSIONS)


def filtered_diff(repo: Path, sha: str) -> str:
    """Diff for one commit, keeping only source-file sections."""
    raw = run(
        ["git", "show", sha, "--format=", "--no-color", "--unified=3"],
        repo,
    )
    kept: list[str] = []
    keep_current = False
    for line in raw.splitlines():
        if line.startswith("diff --git "):
            # "diff --git a/path b/path" -> use the b/ path
            parts = line.split(" b/", 1)
            path = parts[1] if len(parts) == 2 else line
            keep_current = _file_included(path)
        if keep_current:
            kept.append(line)
    return "\n".join(kept).strip()


def cap_commit(diff: str, per_commit_token_cap: int) -> str:
    """Truncate a single commit's diff so no one refactor dominates."""
    char_cap = per_commit_token_cap * CHARS_PER_TOKEN
    if len(diff) <= char_cap:
        return diff
    head = diff[:char_cap]
    return head + f"\n... [diff truncated: {est_tokens(diff)} tokens total, capped at {per_commit_token_cap}]"


def stratified_pick(commits: list[Commit], budget_tokens: int) -> list[Commit]:
    """Keep every commit if we fit; else sample evenly across the timeline.

    Preserves temporal spread: we always keep the first and last commit, then
    thin the middle by an even stride, tightening the stride until we fit.
    """
    total = sum(c.tokens for c in commits)
    if total <= budget_tokens:
        return commits
    n = len(commits)
    # Try increasing stride until the kept set fits the budget.
    for stride in range(2, n + 1):
        idx = sorted(set([0, n - 1] + list(range(0, n, stride))))
        kept = [commits[i] for i in idx]
        if sum(c.tokens for c in kept) <= budget_tokens:
            return kept
    # Fallback: just the newest commit that fits.
    return commits[-1:]


def build_corpus(repo: Path, budget_tokens: int, per_commit_cap: int) -> tuple[str, dict]:
    rows = list_commits(repo)
    commits: list[Commit] = []
    for sha, date, subject in rows:
        diff = cap_commit(filtered_diff(repo, sha), per_commit_cap)
        if not diff:
            continue  # commit touched no source files after filtering
        commits.append(Commit(sha=sha, date=date, subject=subject,
                              diff=diff, tokens=est_tokens(diff)))

    kept = stratified_pick(commits, budget_tokens)

    blocks = []
    for c in kept:
        blocks.append(
            f"===== COMMIT {c.sha[:10]} | {c.date} | {c.subject} =====\n{c.diff}"
        )
    corpus = "\n\n".join(blocks)

    manifest = {
        "repo": str(repo),
        "commits_total": len(rows),
        "commits_with_source": len(commits),
        "commits_kept": len(kept),
        "budget_tokens": budget_tokens,
        "per_commit_token_cap": per_commit_cap,
        "corpus_tokens_est": est_tokens(corpus),
        "kept": [
            {"sha": c.sha[:10], "date": c.date, "subject": c.subject, "tokens": c.tokens}
            for c in kept
        ],
    }
    return corpus, manifest


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract a budget-fitting git history corpus.")
    ap.add_argument("--repo", required=True, help="Path to the git repo to profile.")
    ap.add_argument("--budget", type=int, default=50000,
                    help="Target token budget for the corpus (leave room for output).")
    ap.add_argument("--per-commit-cap", type=int, default=3000,
                    help="Max tokens kept from any single commit's diff.")
    ap.add_argument("--out-dir", default=".", help="Where to write corpus.txt/manifest.json.")
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    if not (repo / ".git").exists():
        sys.exit(f"Not a git repo: {repo}")

    corpus, manifest = build_corpus(repo, args.budget, args.per_commit_cap)

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "corpus.txt").write_text(corpus)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    print(f"commits: {manifest['commits_total']} total, "
          f"{manifest['commits_with_source']} with source, "
          f"{manifest['commits_kept']} kept")
    print(f"corpus: ~{manifest['corpus_tokens_est']} tokens "
          f"(budget {args.budget}) -> {out_dir/'corpus.txt'}")


if __name__ == "__main__":
    main()
