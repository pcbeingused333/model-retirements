#!/usr/bin/env python3
"""Build a standalone, machine-readable feed of LLM model shutdown dates.

Why a feed and not just the linter: the dates are the valuable part and they are useful far
beyond one Python linter. A Go service, a TypeScript CI check or a dashboard should be able to
ask "is the model this code points at still going to be served next month" without installing
anything. So the dates live here, versioned, and llm-drift-lint becomes one consumer of them.

What this adds over reading the four provider pages yourself:
  - one schema across four providers that each publish a different shape;
  - the alias -> snapshot relationships, because an alias of a retired snapshot has nothing
    left to serve even when the provider only lists the snapshot;
  - the platform spellings of each id (Bedrock, Vertex, router prefixes), which is what a
    scanner actually has to match in real source code;
  - an explicit `checked` date per source, so a consumer can tell how stale the feed is.

Usage: build_feed.py <path-to-llm-drift-lint> <out.json>
"""
from __future__ import annotations

import datetime as dt
import json
import sys

# Spellings the same model is written as on other platforms and through routers. Deliberately a
# short, documented list rather than a guess at every gateway's convention.
PREFIXES = {
    "OpenAI": ["openai/", "azure/"],
    "Anthropic": ["anthropic/", "anthropic.", "us.anthropic.", "eu.anthropic.",
                  "apac.anthropic.", "global.anthropic."],
    "Google": ["google/", "gemini/", "models/"],
    "Vertex AI": ["google/", "vertex_ai/", "publishers/google/models/"],
}

# When each provider page was last read. These come from the comments in llm-drift-lint's
# models.py, which is where the table is maintained.
CHECKED = {
    "OpenAI": "2026-10-26",
    "Anthropic": "2026-10-19",
    "Google": "2026-10-26",
    "Vertex AI": "2026-10-19",
}


def main() -> int:
    lint_path, out_path = sys.argv[1], sys.argv[2]
    sys.path.insert(0, f"{lint_path}/src")
    import llm_drift_lint.models as m  # noqa: E402

    today = dt.date.today()
    tables = {
        "openai-api": m.OPENAI_SHUTDOWNS,
        "claude-api": m.CLAUDE_RETIREMENTS,
        "gemini-api": m.GEMINI_SHUTDOWNS,
        "vertex-ai": m.VERTEX_GEMINI_RETIREMENTS,
    }

    models, sources = [], {}
    for platform, table in tables.items():
        for model_id, sd in sorted(table.items()):
            date = dt.date.fromisoformat(sd.date)
            sources.setdefault(sd.provider, {"url": sd.source,
                                             "checked": CHECKED.get(sd.provider, "unknown")})
            models.append({
                "id": model_id,
                "provider": sd.provider,
                "platform": platform,
                "shutdown": sd.date,
                "status": "retired" if date <= today else "scheduled",
                "days_remaining": (date - today).days if date > today else 0,
                "replacement": sd.replacement,
                "also_written_as": [p + model_id for p in PREFIXES.get(sd.provider, [])],
                "source": sd.source,
            })

    models.sort(key=lambda e: (e["shutdown"], e["provider"], e["id"]))
    feed = {
        "schema": "1",
        "generated_at": today.isoformat(),
        "note": ("Shutdown dates as published by each provider. `checked` is when that "
                 "provider's page was last read by hand; a date can move, so treat anything "
                 "older than a few weeks as needing a re-read."),
        "sources": sources,
        "counts": {
            "total": len(models),
            "retired": len([e for e in models if e["status"] == "retired"]),
            "scheduled": len([e for e in models if e["status"] == "scheduled"]),
        },
        "models": models,
    }
    json.dump(feed, open(out_path, "w"), indent=1)

    print(f"{len(models)} models across {len(tables)} platforms -> {out_path}")
    print(f"  retired already: {feed['counts']['retired']}")
    print(f"  still scheduled: {feed['counts']['scheduled']}")
    print("\n--- shutting down in the next 120 days")
    soon = [e for e in models if e["status"] == "scheduled" and e["days_remaining"] <= 120]
    for e in soon:
        print(f"  {e['shutdown']}  ({e['days_remaining']:>3}d)  {e['provider']:<18} "
              f"{e['id']:<34} -> {e['replacement']}")
    if not soon:
        print("  nothing")
    print("\n--- source freshness")
    for prov, s in sorted(sources.items()):
        age = (today - dt.date.fromisoformat(s["checked"])).days if s["checked"] != "unknown" else None
        print(f"  {prov:<18} checked {s['checked']}" + (f"  ({age}d ago)" if age is not None else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
