#!/usr/bin/env python3
"""Build a single self-contained HTML showing ALL states at once.

The normal snapshot only captures Act 1, because Act 2/3 need button clicks.
For a design handoff we want every state visible on one page, so this inlines
real captured outputs and auto-renders the live-check + commit-proposal views.
"""
import json
from pathlib import Path

ROOT = Path(__file__).parent

# Real outputs captured from actual gemma4:e4b runs (see README for the commands).
LIVE_RESULT = {
    "verdict": "The developer is continuing their pattern of ambitious feature engineering and adding complex metrics. While the new features are technically advanced, they introduce potential mathematical instability (zero division/NaNs) that require explicit defensive coding to maintain robustness.",
    "matches": [
        {
            "pattern_name": "Overly complex/redundant feature engineering and data source integration",
            "confidence": "high",
            "why": "The addition of three new, highly specific features (`rel_volume`, `price_vs_vwap`, `gap_ratio`) significantly increases the complexity of the `enrich_for_ml` function. This aligns with the developer's history of adding multiple advanced metrics and signals (e.g., MACD, BB Width) into core feature calculation functions.",
            "related_shas": ["ee1664bdb0", "d2450c54da", "b32f4ad93d"],
            "suggestion": "Consider grouping these new features into a separate, optional feature module or limiting the number of added metrics to prevent code bloat.",
        },
        {
            "pattern_name": "Repeated failure to handle non-numeric/missing data in financial calculations (NaN/None checks)",
            "confidence": "medium",
            "why": "The calculation for `price_vs_vwap` involves division by a cumulative sum (`vwap`) which could result in zero or NaN values, especially at the start of the dataset or if volume is zero. The current implementation lacks explicit handling (e.g., `.replace(0, np.nan)` or an epsilon addition) to ensure mathematical stability.",
            "related_shas": ["ccf5067498", "ee1664bdb0", "d2450c54da"],
            "suggestion": "Wrap the VWAP calculation or the final division with a check for zero denominators, e.g., `out['price_vs_vwap'] = (c - vwap) / vwap.replace(0, np.nan)`.",
        },
    ],
}

COMMIT_MSG = """feat(indicators): Add relative volume, VWAP ratio, and gap features

This update enriches the feature set in `enrich_for_ml` by adding three specialized metrics: relative volume (`rel_volume`), price-to-VWAP deviation (`price_vs_vwap`), and open/previous close gap ratio (`gap_ratio`).

⚠️ Developer Pattern Alert:
1. Data Robustness (NaN/Zero Handling): The introduction of multiple rolling window calculations, cumulative sums, and divisions significantly increases the risk of encountering zero volumes or NaN values at data boundaries. This pattern echoes previous issues in `ccf5067498`, `ee1664bdb0`, and `d2450c54da`. Robust checks for division by zero should be implemented immediately.
2. Feature Bloat (Swiss Army Knife): The function continues to accumulate highly specialized, distinct feature groups into a single method (`enrich_for_ml`). This pattern of adding complexity rather than simplifying or optimizing core logic is evident in `ee1664bdb0` and `d2450c54da`. Consider modularizing these indicators into separate calculation services to improve maintainability."""

COMMIT_RESULT = {"sha": "c479c1b", "log": "c479c1b feat(indicators): Add relative volume, VWAP ratio, and gap features"}


def main() -> None:
    html = (ROOT / "web" / "index.html").read_text()
    profile = json.loads((ROOT / "developer_profile.json").read_text())
    manifest = json.loads((ROOT / "manifest.json").read_text())
    diff = (ROOT / "demo_new.diff").read_text()

    inject = (
        "<script>"
        f"window.__PROFILE__={json.dumps(profile)};"
        f"window.__MANIFEST__={json.dumps(manifest)};"
        f"window.__DEMO_DIFF__={json.dumps(diff)};"
        f"window.__DEMO_LIVE__={json.dumps(LIVE_RESULT)};"
        f"window.__DEMO_COMMIT__={json.dumps(COMMIT_MSG)};"
        f"window.__DEMO_COMMIT_RESULT__={json.dumps(COMMIT_RESULT)};"
        "</script>"
    )
    html = html.replace("<script>", inject + "\n<script>", 1)
    out = ROOT / "design_handoff.html"
    out.write_text(html)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
