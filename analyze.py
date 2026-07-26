#!/usr/bin/env python3
"""Repo discovery + on-demand analysis, so anyone can point this at their own
projects instead of a hard-coded list.

  discover()      -> git repos on this machine (name, path, commits, language)
  start_analyze() -> build a profile for a chosen set of repos, cached by set

Analysis is the slow part (local Gemma, minutes), so it runs in a background
thread with a polled status, and every completed set is cached so re-selecting
the same projects is instant.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import prepare_multi

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"
STATUS: dict = {"state": "idle", "step": "", "error": "", "key": ""}
_LOCK = threading.Lock()

_SKIP_DIRS = {"node_modules", "Library", "Applications", ".Trash", "Music",
              "Movies", "Pictures", "go", "venv", ".venv", "__pycache__"}


def default_author() -> str:
    r = subprocess.run(["git", "config", "user.email"], capture_output=True, text=True)
    return (r.stdout.strip() or "").split("@")[0]


def _git(repo: Path, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True).stdout


def _repo_info(repo: Path, author: str) -> dict | None:
    total = len(_git(repo, "log", "--oneline").splitlines())
    if total < 3:
        return None
    mine = len(_git(repo, "log", "--oneline", "--author", author).splitlines()) if author else total
    py = len(_git(repo, "ls-files", "*.py").splitlines())
    js = len(_git(repo, "ls-files", "*.js", "*.ts", "*.tsx").splitlines())
    lang = "Python" if py >= js else ("JS/TS" if js else "—")
    return {"name": repo.name, "path": str(repo), "commits": total,
            "mine": mine, "py": py, "js": js, "lang": lang}


def discover(author: str = "", limit: int = 60) -> list[dict]:
    author = author or default_author()
    home = str(Path.home())
    repos: list[dict] = []
    for dirpath, dirnames, _ in os.walk(home):
        if ".git" in dirnames:                      # a repo root
            repo = Path(dirpath)
            if str(repo) != str(ROOT):
                info = _repo_info(repo, author)
                if info:
                    repos.append(info)
            dirnames[:] = []                        # don't descend into a repo
            continue
        depth = os.path.relpath(dirpath, home).count(os.sep)
        if depth >= 4:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS]
        if len(repos) >= limit:
            break
    # yours first (most authored commits), then biggest
    repos.sort(key=lambda r: (-r["mine"], -r["commits"]))
    return repos


def _key(paths: list[str]) -> str:
    return hashlib.sha1("|".join(sorted(paths)).encode()).hexdigest()[:16]


def _restore(cache_dir: Path) -> None:
    for f in ("corpus.txt", "manifest.json", "developer_profile.json"):
        if (cache_dir / f).exists():
            shutil.copy(cache_dir / f, ROOT / f)


def _run(repos: list[dict], author: str, key: str) -> None:
    try:
        with _LOCK:
            STATUS["step"] = f"reading history across {len(repos)} projects"
        pairs = [(r["name"], Path(r["path"])) for r in repos]
        corpus, manifest = prepare_multi.build(pairs, author, 30000, 2000)
        (ROOT / "corpus.txt").write_text(corpus)
        (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2))
        with _LOCK:
            STATUS["step"] = "reading your code with Gemma 4 (a few minutes, fully local)"
        r = subprocess.run(["python3", "build_profile.py", "--model", "gemma4:e4b",
                            "--num-ctx", "40000"], cwd=str(ROOT), capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout)[-400:] or "build failed")
        cache_dir = CACHE / key
        cache_dir.mkdir(parents=True, exist_ok=True)
        for f in ("corpus.txt", "manifest.json", "developer_profile.json"):
            shutil.copy(ROOT / f, cache_dir / f)
        with _LOCK:
            STATUS.update(state="done", step="done")
    except Exception as e:  # noqa: BLE001
        with _LOCK:
            STATUS.update(state="error", error=str(e))


def start_analyze(repos: list[dict], author: str = "") -> dict:
    author = author or default_author()
    if not repos:
        return {"state": "error", "error": "no projects selected"}
    key = _key([r["path"] for r in repos])
    with _LOCK:
        if STATUS["state"] == "running":
            return {"state": "running"}
        STATUS.update(state="running", step="starting", error="", key=key)
    cache_dir = CACHE / key
    if (cache_dir / "developer_profile.json").exists():
        _restore(cache_dir)
        with _LOCK:
            STATUS.update(state="done", step="cached")
        return {"state": "done", "cached": True}
    threading.Thread(target=_run, args=(repos, author, key), daemon=True).start()
    return {"state": "running"}


def status() -> dict:
    with _LOCK:
        return dict(STATUS)


def seed_cache(paths: list[str]) -> str:
    """Seed the cache for an already-built set (so the demo selection is instant)."""
    key = _key(paths)
    cache_dir = CACHE / key
    cache_dir.mkdir(parents=True, exist_ok=True)
    for f in ("corpus.txt", "manifest.json", "developer_profile.json"):
        if (ROOT / f).exists():
            shutil.copy(ROOT / f, cache_dir / f)
    return key
