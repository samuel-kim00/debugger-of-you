#!/usr/bin/env python3
"""Tiny stdlib-only client for a local Ollama server.

No pip installs — just urllib. Forces the context window per request via
options.num_ctx, which beats the /set-parameter + /save dance: Ollama otherwise
silently defaults to a 4096 context and would truncate the whole history.
"""
from __future__ import annotations

import json
import urllib.request

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "gemma4:e4b"


def generate(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    num_ctx: int = 65536,
    host: str = DEFAULT_HOST,
    fmt: dict | str | None = None,
    temperature: float = 0.2,
    timeout: int = 1800,
) -> str:
    """One-shot completion. Returns the raw response string.

    fmt: pass "json" or a JSON schema dict to constrain output.
    """
    body: dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        # num_predict explicit and large: the profile JSON is long, and the
        # default cut generation off mid-object on the deeper multi-repo schema.
        "options": {"num_ctx": num_ctx, "num_predict": 16384, "temperature": temperature},
    }
    if fmt is not None:
        body["format"] = fmt

    req = urllib.request.Request(
        f"{host}/api/generate",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    return payload.get("response", "")


def chat_with_tools(
    messages: list[dict],
    tools: list[dict],
    *,
    model: str = DEFAULT_MODEL,
    num_ctx: int = 16384,
    host: str = DEFAULT_HOST,
    temperature: float = 0.2,
    timeout: int = 600,
) -> dict:
    """Native function-calling chat. Returns the assistant message dict,
    which carries `tool_calls` when the model decides to call a tool.
    """
    body = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "stream": False,
        "options": {"num_ctx": num_ctx, "temperature": temperature},
    }
    req = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    return payload.get("message", {})


def _repair(s: str) -> str:
    import re
    s = s.strip()
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end != -1:
        s = s[start : end + 1]
    s = re.sub(r",(\s*[}\]])", r"\1", s)   # drop trailing commas
    return s


def generate_json(prompt: str, schema: dict, **kwargs) -> dict:
    """generate() constrained to a JSON schema, parsed into a dict.

    Grammar-constrained decoding is usually valid, but a 4B model occasionally
    emits a malformed object; we try a light repair and, failing that, dump the
    raw text so the run can be diagnosed without re-invoking the model."""
    import pathlib
    raw = generate(prompt, fmt=schema, **kwargs)
    for candidate in (raw, _repair(raw)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    pathlib.Path("/tmp/gemma_raw.json").write_text(raw)
    raise ValueError("model returned unparseable JSON (raw saved to /tmp/gemma_raw.json)")
