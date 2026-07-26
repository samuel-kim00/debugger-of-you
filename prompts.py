#!/usr/bin/env python3
"""Prompt templates and JSON schemas for the two Gemma passes."""
from __future__ import annotations

# --- Stage 1: build the "Coding Autobiography" from the whole history --------

PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "patterns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": ["bug", "style", "architecture", "process"],
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                    "occurrences": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "string"},
                    "first_seen": {"type": "string"},
                    "last_seen": {"type": "string"},
                },
                "required": ["name", "description", "category", "occurrences", "evidence"],
            },
        },
        "style_drift": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "aspect": {"type": "string"},
                    "early": {"type": "string"},
                    "recent": {"type": "string"},
                },
                "required": ["aspect", "early", "recent"],
            },
        },
        "temporal_habits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "habit": {"type": "string"},
                    "detail": {"type": "string"},
                },
                "required": ["habit", "detail"],
            },
        },
    },
    "required": ["patterns", "style_drift", "temporal_habits"],
}

PROFILE_PROMPT = """You are a senior engineer writing ONE developer's "Coding \
Autobiography" from their entire git history at once.

You are given many commits, oldest to newest, each as:
  ===== COMMIT <sha> | <date> | <subject> =====
  <diff>

Your job is the thing no per-commit review can do: find patterns that only \
appear when you see MONTHS of history together.

Focus on:
1. patterns — recurring bug types or mistakes the SAME developer makes again and \
   again across DIFFERENT commits and dates (e.g. "repeatedly forgets to guard \
   against zero/None before division", "keeps re-fixing the same integer-vs-float \
   API constraint"). For each, list the commit shas where it shows up, cite \
   concrete evidence from the diffs, and give first_seen / last_seen dates.
2. style_drift — how their coding style changed from the earliest to the latest \
   commits (naming, typing, error handling, structure).
3. temporal_habits — habits visible only over time (e.g. "fixes bugs in bursts \
   right after adding a feature", "commits large refactors then patches them").

Only report a pattern if it genuinely appears in MULTIPLE commits. Be specific \
and cite shas. No generic advice. Output must match the provided JSON schema.

=== GIT HISTORY ===
{corpus}
"""


def profile_prompt(corpus: str) -> str:
    return PROFILE_PROMPT.format(corpus=corpus)


# --- Stage 2: live-check a new diff against the cached profile ----------------

LIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pattern_name": {"type": "string"},
                    "confidence": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                    "why": {"type": "string"},
                    "related_shas": {"type": "array", "items": {"type": "string"}},
                    "suggestion": {"type": "string"},
                },
                "required": ["pattern_name", "confidence", "why"],
            },
        },
        "verdict": {"type": "string"},
    },
    "required": ["matches", "verdict"],
}

LIVE_PROMPT = """You are checking a NEW, uncommitted diff against a developer's \
known history of recurring patterns (their "Coding Autobiography").

Here is their profile of recurring patterns, as JSON:
{profile}

Here is the new diff they are about to commit:
=== NEW DIFF ===
{diff}

Decide whether this diff repeats any of the KNOWN patterns above. For each match, \
name the pattern, give confidence, explain WHY it matches (cite the specific lines \
in the new diff), reference the related past commit shas from the profile, and give \
a concrete one-line fix suggestion. If nothing matches, return an empty matches \
array. Write a short overall verdict. Output must match the provided JSON schema.
"""


def live_prompt(profile_json: str, diff: str) -> str:
    return LIVE_PROMPT.format(profile=profile_json, diff=diff)
