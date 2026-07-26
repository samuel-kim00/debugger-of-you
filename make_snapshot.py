#!/usr/bin/env python3
"""Inline profile + manifest into a standalone HTML (no backend needed).

Handy for previewing the Act 1 report and for a shareable demo artifact.
The Act 2 live check still needs the server; this is a static snapshot.
"""
import json
from pathlib import Path

ROOT = Path(__file__).parent
html = (ROOT / "web" / "index.html").read_text()
profile = json.loads((ROOT / "developer_profile.json").read_text())
manifest = json.loads((ROOT / "manifest.json").read_text())

inject = (
    "<script>window.__PROFILE__=" + json.dumps(profile)
    + ";window.__MANIFEST__=" + json.dumps(manifest) + ";</script>"
)
html = html.replace("<script>", inject + "\n<script>", 1)
out = ROOT / "demo_snapshot.html"
out.write_text(html)
print(f"wrote {out}")
