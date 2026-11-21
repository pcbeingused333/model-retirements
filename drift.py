#!/usr/bin/env python3
"""Compare a hand-maintained shutdown table against what the provider's page says today.

This is the feed's reason to exist, made measurable: every row of disagreement is a case where
a tool trusting the stale table would give a user the wrong answer.

Usage: drift.py <feed.json> <live.json> <provider>
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    feed = json.load(open(sys.argv[1]))
    live = json.load(open(sys.argv[2]))
    provider = sys.argv[3]

    held = {e["id"]: e for e in feed["models"] if e["provider"] == provider}
    now = {e["id"]: e for e in live["models"]}

    print(f"provider: {provider}")
    print(f"  held in the table: {len(held)}")
    print(f"  on the page today: {len(now)}  (upcoming deprecations only)")

    wrong_date, wrong_repl, missing, gone = [], [], [], []
    for mid, e in sorted(now.items()):
        h = held.get(mid)
        if h is None:
            missing.append(e)
            continue
        if e["shutdown"] and h["shutdown"] != e["shutdown"]:
            wrong_date.append((mid, h["shutdown"], e["shutdown"]))
        hr, er = h["replacement"].split(), e["replacement"].split()
        if hr and er and hr[0] != er[0]:
            wrong_repl.append((mid, h["replacement"], e["replacement"]))
    for mid, h in sorted(held.items()):
        if mid not in now and h["status"] == "scheduled":
            gone.append((mid, h["shutdown"]))

    print(f"\n[1] WRONG REPLACEMENT RECOMMENDED  ({len(wrong_repl)})")
    for mid, was, now_ in wrong_repl:
        print(f"    {mid:<28} table says {was!r}")
        print(f"    {'':<28} page says  {now_!r}")
    print(f"\n[2] WRONG SHUTDOWN DATE  ({len(wrong_date)})")
    for mid, was, now_ in wrong_date:
        print(f"    {mid:<28} table {was}  page {now_}")
    print(f"\n[3] ON THE PAGE, ABSENT FROM THE TABLE  ({len(missing)})")
    for e in missing:
        print(f"    {(e['shutdown'] or 'undated'):<10}  {e['id']:<34} -> {e['replacement'][:46]}"
              f"  [{e.get('date_certainty', '')}]")
    print(f"\n[4] SCHEDULED IN THE TABLE, NOT ON THE PAGE  ({len(gone)})")
    for mid, d in gone:
        print(f"    {mid:<28} table says {d}; page does not list it")
    print("\nA tool trusting the table would be wrong on "
          f"{len(wrong_repl) + len(wrong_date)} model(s) and silent on {len(missing)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
