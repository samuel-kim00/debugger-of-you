# The Debugger of You

**Your coding autobiography, read in one context by local Gemma 4.**
Track: Edge / On-Device.

Every AI code reviewer and commit-message tool on the market looks at **one diff
at a time**. That means they can never see the thing that actually defines a
developer: *the mistake you keep making across months.*

**The Debugger of You** feeds your **entire git history into a single Gemma 4
context — no per-diff chunking** — and writes a "Coding Autobiography": the bug
patterns, style drift, and habits that only emerge when months of commits are
read together. It then caches that profile and uses it to **live-check any new
diff** against your own track record in seconds.

Because it runs on a local Gemma 4 via Ollama, it works fully offline and your
private codebase never leaves your machine.

---

## Why this needs Gemma 4 specifically

- **Long context is the whole trick.** The differentiator is reading the full
  history at once. That is a direct, honest answer to "why do you need a long
  context window" — without it, this product cannot exist.
- **On-device / offline.** Your source history is private. A cloud model would
  mean shipping your entire codebase to a third party. Local Gemma 4 means it
  never leaves the laptop.
- **Native function calling** lets the live-check auto-write a commit message that
  knows *why* the change relates to your past: Gemma emits an `execute_git_commit`
  tool call citing the recurring pattern and past SHAs — see Act 3 below.

## Architecture

```
repo git history
      │  prepare_history.py   (filter to source, cap per-commit, stratified sample)
      ▼
   corpus.txt  (~37K tokens, spans the whole timeline)
      │  build_profile.py     (ONE Gemma 4 pass, num_ctx 64K, slow, offline)
      ▼
developer_profile.json  ← cached to disk, built once
      │  live_check.py        (new diff + profile only — never reloads history)
      ▼
   "This repeats pattern #2 — same cause you fixed in <sha>"
```

### The 64K scope decision (honest engineering note)

Gemma 4's true 256K context lives on the 26B/31B models, which don't fit in
16GB. We standardize on **`gemma4:e4b`** (128K-capable, effective-4B edge model)
and run it at **`num_ctx` 64K**, which is what an M1/16GB actually sustains. A
real repo's Python history is ~196K tokens, so `prepare_history.py` filters out
AI-generated docs and generated files, caps any single commit, and
stratified-samples across the timeline to land near ~37K tokens — preserving the
"evolution over time" story while fitting the budget.

**Gotcha we hit:** Ollama silently defaults to a 4096 context. We force it per
request with `options.num_ctx` instead of the `/set parameter` + `/save` dance.

## Setup

```bash
# 1. model (7GB)
ollama pull gemma4:e4b

# 2. build the corpus from any repo you own
python3 prepare_history.py --repo /path/to/your/repo --budget 50000

# 3. build the profile (slow, one-shot, offline)
python3 build_profile.py

# 4. run the demo UI
python3 server.py         # http://localhost:8777
```

No pip installs — everything uses the Python standard library plus a local
Ollama server.

## Files

| file | role |
|------|------|
| `prepare_history.py` | Stage 0 — git history → budget-fitting corpus (model-free) |
| `build_profile.py`   | Stage 1 — corpus → `developer_profile.json` (one Gemma pass) |
| `live_check.py`      | Stage 2 — new diff vs profile (fast, live) |
| `commit_capstone.py` | Stage 3 — Gemma function call writes a history-aware commit |
| `server.py`          | stdlib backend for the demo |
| `web/index.html`     | single-page UI: autobiography + live check |
| `ollama_client.py`   | tiny urllib client, forces `num_ctx` |
| `prompts.py`         | prompts + JSON schemas for both passes |

## Demo (2 acts)

1. **Act 1** (pre-built): the Coding Autobiography — commit timeline + the
   recurring-pattern cards.
2. **Act 2** (live, on stage): paste a fresh diff, watch it get flagged against
   your own history in seconds — with the past commit shas where you did it before.
3. **Act 3** (function calling): click "Write a history-aware commit" — Gemma emits
   an `execute_git_commit` tool call whose message cites the pattern and past shas;
   approve it and the commit lands in a scratch repo.
