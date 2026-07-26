# The Debugger of You

**Your coding autobiography — the mistakes you repeat across all your projects, read
in one local Gemma 4 pass.**
Track: Edge / On-Device.

Every AI code reviewer and commit-message tool looks at **one diff at a time**. So
they can never see the thing that actually defines a developer: *the mistake you make
in every project.*

**The Debugger of You** reads your history across **several of your projects at once,
in a single Gemma 4 context — no per-diff chunking, no RAG** — and writes a "Coding
Autobiography": your recurring mistakes, ranked by severity, each with a concrete fix.
A pattern that shows up in **more than one project** is flagged as *your* habit, not
the project's. It then live-checks any new diff against that profile in seconds, and
uses Gemma 4's **native function calling** to write a history-aware commit.

It runs on a local Gemma 4 via Ollama, so it works **fully offline** and your source
never leaves the machine.

---

## Why this needs Gemma 4 (Edge / On-Device)

- **Long context is the whole trick** — reading a full, multi-project history in one
  window is the differentiator. Without it, the product cannot exist.
- **On-device is mandatory** — your source is private; a cloud model would mean
  uploading your whole codebase. Local Gemma 4 means it never leaves the laptop.
- **Native function calling** — Gemma emits an `execute_git_commit` tool call whose
  message cites the past commits the change echoes.

## Architecture

```
discover local git repos   (analyze.py — name, language, YOUR commit share)
        │  pick projects in the browser
        ▼
prepare_multi.py   keep only YOUR commits, tag each by project,
                   stratified-sample across repos → one ~26K-token corpus
        ▼
build_profile.py   ONE Gemma 4 pass (num_ctx 40K, offline) → patterns JSON
        ▼
verify()           drop any cited line not in the real commit; drop patterns that
                   don't span 2+ commits on 2+ dates; flag 2+ project patterns
        ▼
developer_profile.json    ← cached per project-set (re-selecting is instant)
        │
        ├─ Act 1  patterns × projects matrix, severity, fix, real-code side panel
        ├─ Act 2  live_check.py — new diff vs profile in ~25s (never reloads history)
        └─ Act 3  commit_capstone.py — Gemma function call writes the commit
```

**Two guarantees that make the 4B model trustworthy:**
1. **Grounding** — every line the model cites is checked against the real commit and
   dropped if not found. Everything shown is real.
2. **Recurrence** — a pattern must span 2+ commits on 2+ dates; three lines in one
   commit is not a habit.

**Scope decision:** Gemma 4's true 256K lives on the 26B/31B models, which don't fit
in 16GB. We use **`gemma4:e4b`** (128K-capable edge model) at a `num_ctx` an M1/16GB
sustains (100% GPU, 3.4GB). *Gotcha:* Ollama silently defaults to a 4096 context — we
force it per request with `options.num_ctx`.

## Setup

```bash
ollama pull gemma4:e4b        # 7GB, one time
cd debugger-of-you
python3 server.py             # http://localhost:8777 — no pip installs
```

Open `http://localhost:8777`, pick projects from the auto-discovered list, and click
**Analyze**. The first run for a project set reads them locally with Gemma (a few
minutes); every set is cached so re-selecting is instant. Everything is Python
standard library plus a local Ollama server.

## Files

| file | role |
|------|------|
| `analyze.py`         | discover local repos + build/cache a profile for a chosen set |
| `prepare_multi.py`   | combine several repos (your commits, tagged, sampled) → corpus |
| `prepare_history.py` | per-repo source-diff extraction used by `prepare_multi` |
| `build_profile.py`   | one Gemma 4 pass → profile, then `verify()` grounds + filters it |
| `live_check.py`      | Act 2 — new diff vs profile (fast, live) |
| `commit_capstone.py` | Act 3 — Gemma function call writes a history-aware commit |
| `server.py`          | stdlib backend (`/api/repos`, `/api/analyze`, `/api/live-check`, …) |
| `web/index.html`     | single-page UI: picker → autobiography → live check → commit |
| `ollama_client.py`   | tiny urllib client; forces `num_ctx`/`num_predict`, repairs JSON |
| `prompts.py`         | prompts + JSON schemas for the Gemma passes |

## The three acts

1. **Act 1 — Coding Autobiography.** A patterns × projects matrix (a row lit in 2+
   columns is a cross-project habit), each pattern with severity, a fix, and a side
   panel showing your real code from every commit, offending lines highlighted.
2. **Act 2 — Live Check.** Paste a fresh diff; it's flagged against your profile in
   seconds, citing the past commits where you did it before.
3. **Act 3 — Function-calling commit.** Gemma emits an `execute_git_commit` tool call
   whose message cites the pattern and past SHAs; approve it and it commits.

See `DEMO_SCRIPT.md` for the recording walkthrough.
