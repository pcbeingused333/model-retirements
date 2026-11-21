#!/usr/bin/env python3
"""Parse Google Cloud's Vertex AI model-versions page into feed entries.

Vertex retires Gemini models on its own schedule, separate from the Gemini API, so these stay
on the `vertex-ai` platform. The page states how to read its dates and the parser keeps that
meaning rather than flattening it:

    "While retirement timelines may be extended, they won't be moved to an earlier date than
     what is listed."

so a GA model's date is a floor, not a promise. Dates are therefore tagged:
    firm              a fixed date, or a date already past (retired)
    not_earlier_than  the page says "or later"
    unannounced       "No retirement date announced": there is no date to put in a feed

Usage: parse_vertex.py <vertex.html> <out.json>
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
import html_tables  # noqa: E402

SOURCE = "https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/model-versions"
FULL = re.compile(r"^(?:(?:No|Not) sooner than\s+)?([A-Z][a-z]+) (\d{1,2}), (\d{4})(\s+or later)?$",
                  re.I)
FLOOR = re.compile(r"^(?:No|Not) sooner than\s", re.I)
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June",
                                      "July", "August", "September", "October", "November",
                                      "December"], 1)}


def parse_date(cell: str):
    cell = cell.strip()
    if cell.lower().startswith("no retirement date"):
        return None, "unannounced"
    mo = FULL.match(cell)
    if not mo or mo.group(1).capitalize() not in MONTHS:
        return None, "unparsed"
    iso = f"{mo.group(3)}-{MONTHS[mo.group(1).capitalize()]:02d}-{int(mo.group(2)):02d}"
    floor = bool(mo.group(4)) or bool(FLOOR.match(cell))
    return iso, ("not_earlier_than" if floor else "firm")


def main() -> int:
    today = dt.date.today()
    entries, unparsed, per_table = [], [], []
    for t in html_tables.tables(sys.argv[1]):
        head = [h.lower() for h in t[0]]
        if "model id" not in head or not any("retirement date" in h for h in head):
            continue
        i_id, i_rel = head.index("model id"), next((i for i, h in enumerate(head) if "release" in h), None)
        i_ret = next(i for i, h in enumerate(head) if "retirement date" in h)
        i_rep = next((i for i, h in enumerate(head) if "replacement" in h or "upgrade" in h), None)
        n0 = len(entries)
        for row in t[1:]:
            if len(row) <= max(i_id, i_ret):
                continue
            iso, certainty = parse_date(row[i_ret])
            if certainty == "unparsed":
                unparsed.append((row[i_id], row[i_ret]))
                continue
            released = row[i_rel] if i_rel is not None and i_rel < len(row) else ""
            repl = row[i_rep] if i_rep is not None and i_rep < len(row) else ""
            past = bool(iso) and dt.date.fromisoformat(iso) <= today
            floor = certainty == "not_earlier_than"
            retired = past and not floor
            entries.append({
                "id": row[i_id], "provider": "Vertex AI", "platform": "vertex-ai",
                "shutdown": iso, "shutdown_as_published": row[i_ret],
                "date_certainty": certainty,
                "status": "retired" if retired else "active" if (floor or not iso) else "scheduled",
                "days_remaining": (max(0, (dt.date.fromisoformat(iso) - today).days)
                                   if iso and not retired else 0),
                "replacement": repl, "released": released, "source": SOURCE,
            })
        per_table.append((head, len(entries) - n0))

    json.dump({"source": SOURCE, "read_on": today.isoformat(), "models": entries},
              open(sys.argv[2], "w"), indent=1)
    print(f"{len(entries)} model rows from {len(per_table)} tables -> {sys.argv[2]}")
    for head, n in per_table:
        print(f"   {n:>3} rows   columns: {' | '.join(head)}")
    if unparsed:
        print(f"\n!! {len(unparsed)} rows whose date did not parse (kept out, not guessed):")
        for mid, cell in unparsed[:15]:
            print(f"   {mid!r}: {cell!r}")
    import collections
    print("\nby status/certainty:")
    for k, n in sorted(collections.Counter((e["status"], e["date_certainty"]) for e in entries).items()):
        print(f"   {n:>3}  {k[0]:<10} {k[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
