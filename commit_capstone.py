#!/usr/bin/env python3
"""Stretch goal: history-aware commit message via Gemma 4 native function calling.

What makes this different from opencommit / aicommits: those write a message from
the diff alone. Here the model is handed the developer's recurring-pattern matches
(from live_check) and asked to write a message that says WHY this change relates to
their past — then it emits an `execute_git_commit` tool call, which we run against a
scratch demo repo so the agentic loop visibly closes (model decides -> tool runs ->
real commit) without touching the real project.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import ollama_client

COMMIT_TOOL = [{
    "type": "function",
    "function": {
        "name": "execute_git_commit",
        "description": "Create a git commit with the given message once the user approves.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Full commit message. Subject line, then a body that "
                                   "references the recurring pattern and the past commit "
                                   "SHAs this change relates to.",
                },
            },
            "required": ["message"],
        },
    },
}]

SYSTEM = (
    "You are a git assistant that writes commit messages aware of the developer's "
    "whole history, not just the current diff. When given a diff and the recurring "
    "patterns it touches, write a conventional-commits message whose body notes the "
    "recurring pattern and cites the past commit SHAs where it appeared. Then call "
    "execute_git_commit with that message. Keep the subject under 72 chars."
)


def propose_commit(diff: str, matches: list[dict], model: str = ollama_client.DEFAULT_MODEL) -> dict:
    """Ask Gemma to emit an execute_git_commit tool call. Returns {message, tool_call}."""
    pattern_note = "\n".join(
        f"- {m.get('pattern_name')}: relates to past commits "
        f"{', '.join(m.get('related_shas', []))}. {m.get('why','')}"
        for m in matches
    ) or "- (no known patterns matched)"

    user = (
        f"New diff about to be committed:\n{diff}\n\n"
        f"Recurring patterns this diff touches (from the developer's history):\n{pattern_note}\n\n"
        "Write the commit message and call execute_git_commit."
    )
    msg = ollama_client.chat_with_tools(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        COMMIT_TOOL,
        model=model,
    )
    calls = msg.get("tool_calls") or []
    if calls:
        args = calls[0]["function"]["arguments"]
        message = args.get("message", "") if isinstance(args, dict) else str(args)
        return {"message": message, "tool_call": calls[0]}
    # Fallback: model answered in prose instead of calling the tool.
    return {"message": msg.get("content", "").strip(), "tool_call": None}


def _scratch_repo() -> Path:
    """A throwaway git repo so the demo commit never touches a real project."""
    repo = Path(__file__).parent / "demo_repo"
    if not (repo / ".git").exists():
        repo.mkdir(exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Debugger Demo"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "demo@local"], cwd=repo, check=True)
    return repo


def apply_commit(message: str) -> dict:
    """Run the model's proposed commit in the scratch repo. Returns {sha, log}."""
    repo = _scratch_repo()
    (repo / "change.txt").write_text(f"applied at commit time\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", message], cwd=repo, check=True)
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo,
                         capture_output=True, text=True).stdout.strip()
    log = subprocess.run(["git", "log", "--oneline", "-3"], cwd=repo,
                        capture_output=True, text=True).stdout.strip()
    return {"sha": sha, "log": log}


if __name__ == "__main__":
    import sys
    diff = Path(sys.argv[1]).read_text() if len(sys.argv) > 1 else sys.stdin.read()
    result = ollama_client  # keep import used
    proposed = propose_commit(diff, [])
    print("PROPOSED MESSAGE:\n" + proposed["message"])
    if "--apply" in sys.argv:
        print("\nAPPLIED:", apply_commit(proposed["message"]))
