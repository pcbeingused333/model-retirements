#!/usr/bin/env python3
"""Build feed.json from the provider-page parsers, keeping only what no page can confirm
from the hand-maintained seed, and marking it unverified.

Why this shape: a feed made of transcribed dates drifts (25 days produced 6 wrong replacements
and 41 missing models against OpenAI alone). Every entry that a parser read from a provider's
page today is `verified: true` with the date it was read. Entries that come only from the seed,
such as past retirements the pages no longer list and aliases the pages never mention, are
kept because they are useful to a scanner, but they are `verified: false` and a consumer can
see that.

Spellings: an id is also written with a router or resource prefix, but only where the
provider's own page says the date applies there. Anthropic's page says its dates are for the
platforms Anthropic operates and that Amazon Bedrock and Google-managed Vertex AI set their own
schedules, so `anthropic.claude-...` and `us.anthropic.claude-...` are deliberately NOT listed.
The same goes for `azure/` on OpenAI ids.

Usage: merge_feed.py <seed_feed.json> <out.json> <live.json> [<live.json> ...]
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import sys

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feedlib  # noqa: E402

PREFIXES = {
    "claude-api": ["anthropic/"],
    "openai-api": ["openai/"],
    "gemini-api": ["gemini/", "models/"],
    "vertex-ai": ["vertex_ai/", "publishers/google/models/"],
}
PROVIDER = {"claude-api": "Anthropic", "openai-api": "OpenAI", "gemini-api": "Google",
            "vertex-ai": "Vertex AI"}


def main() -> int:
    seed_path, out_path, *live_paths = sys.argv[1:]
    today = dt.date.today()
    seed = json.load(open(seed_path))
    models, sources = {}, {}

    for path in live_paths:
        live = json.load(open(path))
        for e in live["models"]:
            platform = e["platform"]
            e = dict(e)
            e["verified"] = True
            e["verified_on"] = live["read_on"]
            e["also_written_as"] = [p + e["id"] for p in PREFIXES.get(platform, [])]
            models[(platform, e["id"])] = e
            sources[PROVIDER[platform]] = {"url": live["source"], "read_on": live["read_on"],
                                           "method": "parsed"}

    unverified = 0
    for e in seed["models"]:
        key = (e["platform"], e["id"])
        if key in models:
            continue
        unverified += 1
        platform = e["platform"]
        models[key] = {
            "id": e["id"], "provider": e["provider"], "platform": platform,
            "shutdown": e["shutdown"], "date_certainty": "unknown",
            "replacement": e["replacement"], "verified": False,
            "verified_on": seed["sources"].get(e["provider"], {}).get("checked"),
            "also_written_as": [p + e["id"] for p in PREFIXES.get(platform, [])],
            "source": e["source"],
        }

    # status and days_remaining depend on today's date, so they are not stored: see feedlib.derive.
    for e in models.values():
        e.pop("status", None)
        e.pop("days_remaining", None)
        e.pop("verified_on", None)

    rows = sorted(models.values(), key=lambda e: (e["shutdown"] or "9999", e["provider"], e["id"]))
    feed = {
        "schema": "2",
        "generated_at": today.isoformat(),
        "note": ("Dates as the providers publish them. date_certainty says how to read each: "
                 "firm (already off), announced (a date the provider gave), not_earlier_than "
                 "(a floor, not a promise), unannounced (no date), unknown (not confirmed by "
                 "any page today). verified:false entries were not on any page when this was "
                 "built."),
        "sources": sources,
        "counts": {
            "total": len(rows),
            "verified": len([e for e in rows if e["verified"]]),
            "unverified": unverified,
            "by_certainty": dict(collections.Counter(e["date_certainty"] for e in rows)),
        },
        "models": rows,
    }
    json.dump(feed, open(out_path, "w"), indent=1)

    shown = feedlib.with_derived({"models": [dict(e) for e in rows]}, today)["models"]
    print(f"{len(rows)} entries -> {out_path}   ({feed['counts']['verified']} verified, "
          f"{unverified} carried from the seed unverified)\n")
    print(f"{'provider':<10}{'total':>6}{'verified':>9}{'unverif.':>9}{'retired':>9}{'dated ahead':>12}")
    for prov in ("Anthropic", "OpenAI", "Google", "Vertex AI"):
        es = [e for e in shown if e["provider"] == prov]
        print(f"{prov:<10}{len(es):>6}{len([e for e in es if e['verified']]):>9}"
              f"{len([e for e in es if not e['verified']]):>9}"
              f"{len([e for e in es if e['status'] == 'retired']):>9}"
              f"{len([e for e in es if e['status'] == 'scheduled']):>12}")
    print("\nfirm or announced deadlines in the next 150 days:")
    soon = [e for e in shown if e["status"] == "scheduled" and e["days_remaining"] <= 150
            and e["date_certainty"] in ("firm", "announced")]
    for e in soon:
        print(f"  {e['shutdown']} ({e['days_remaining']:>3}d) {e['provider']:<10} "
              f"{e['id']:<40} -> {e['replacement'][:36]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
