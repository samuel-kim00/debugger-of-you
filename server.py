#!/usr/bin/env python3
"""Minimal stdlib backend for the demo. No Flask, no pip.

Serves the single-page UI and two JSON endpoints:
  GET  /api/profile      -> cached profile + manifest (the Coding Autobiography)
  POST /api/live-check    -> {diff} -> pattern matches against the profile

Everything runs against the local Ollama server, fully offline.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import live_check
import commit_capstone
import prepare_history
from urllib.parse import urlparse, parse_qs


def _repo_for_sha(sha: str):
    m = ROOT / "manifest.json"
    if not m.exists():
        return None
    data = json.loads(m.read_text())
    for k in data.get("kept", []):
        if str(k.get("sha", ""))[:10] == sha[:10] and k.get("path"):
            return Path(k["path"])
    if data.get("repo"):   # backward-compat with single-repo manifests
        return Path(data["repo"])
    return None

ROOT = Path(__file__).parent
PORT = 8777


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json")

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            html = (ROOT / "web" / "index.html").read_bytes()
            return self._send(200, html, "text/html; charset=utf-8")
        if self.path == "/api/profile":
            profile_path = ROOT / "developer_profile.json"
            manifest_path = ROOT / "manifest.json"
            if not profile_path.exists():
                return self._json(404, {"error": "profile not built yet. run build_profile.py"})
            out = {
                "profile": json.loads(profile_path.read_text()),
                "manifest": json.loads(manifest_path.read_text()) if manifest_path.exists() else {},
            }
            return self._json(200, out)
        if self.path.startswith("/api/commit"):
            sha = (parse_qs(urlparse(self.path).query).get("sha") or [""])[0]
            repo = _repo_for_sha(sha)
            if not sha or not repo or not (repo / ".git").exists():
                return self._json(404, {"error": "no repo or sha"})
            diff = prepare_history.filtered_diff(repo, sha)
            subject = prepare_history.run(
                ["git", "log", "-1", "--format=%s%n%ad", "--date=short", sha], repo).strip().split("\n")
            return self._json(200, {
                "sha": sha,
                "subject": subject[0] if subject else "",
                "date": subject[1] if len(subject) > 1 else "",
                "diff": diff[:40000] or "(no source diff)",
            })
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length).decode()) if length else {}
        except json.JSONDecodeError:
            return self._json(400, {"error": "bad json"})
        try:
            if self.path == "/api/live-check":
                diff = req.get("diff", "")
                if not diff.strip():
                    return self._json(400, {"error": "empty diff"})
                return self._json(200, live_check.check_diff(diff, str(ROOT / "developer_profile.json")))
            if self.path == "/api/propose-commit":
                # Gemma 4 native function call: history-aware commit message.
                return self._json(200, commit_capstone.propose_commit(
                    req.get("diff", ""), req.get("matches", [])))
            if self.path == "/api/execute-commit":
                # Runs the model's proposed commit in a scratch repo (never the real project).
                return self._json(200, commit_capstone.apply_commit(req.get("message", "")))
            self._json(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001 - surface any failure to the UI
            self._json(500, {"error": str(e)})

    def log_message(self, *args) -> None:  # quieter console
        pass


if __name__ == "__main__":
    print(f"The Debugger of You — http://localhost:{PORT}  (offline, local Gemma 4)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
