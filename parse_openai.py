#!/usr/bin/env python3
"""Parse OpenAI's deprecations page into feed entries, from its HTML tables.

The page has two model tables whose shapes differ, and the parser reads columns by header name
rather than by position so a reordered or extra column does not silently shift the data:

    Upcoming deprecations   Shutdown date | Affected model | Status | Recommended replacement | Notice date
    Past deprecations       Shutdown date | Affected model or feature | Listed replacement | Notice date

(An earlier version matched the header text "Affected model" exactly, skipped the past table
and let a README claim that the page lists only upcoming deprecations. It does not.)

A "Feature and endpoint deprecations" table also exists; it is not about model ids and is left
out. A model cell like "GPT-4o ( gpt-4o-2024-08-06 , gpt-4o-2024-11-20 )" yields the api ids
inside the parentheses, not the display name. Fine-tuned versions follow their base model's
schedule, as the page states, and are not enumerated here.

Usage: parse_openai.py <openai.html> <out.json>
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
import html_tables  # noqa: E402

SOURCE = "https://developers.openai.com/api/docs/deprecations"
DATE = re.compile(r"^([A-Z][a-z]{2}) (\d{1,2}), (\d{4})$")
MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9.\-]*[a-z0-9]$")


def iso(cell: str):
    mo = DATE.match(cell.strip())
    return f"{mo.group(3)}-{MONTHS[mo.group(1)]:02d}-{int(mo.group(2)):02d}" if mo else None


def is_id(token: str) -> bool:
    """A lowercase api model id: letters and digits, with a digit or a hyphen somewhere."""
    return bool(MODEL_ID.match(token)) and bool(re.search(r"[a-z]", token)) and bool(re.search(r"[\d-]", token))


def ids(cell: str) -> list[str]:
    """The api ids a row retires, or [] when the row is about something else.

    A row counts as a model row only in these shapes, because the page also lists features, prices
    and settings in the same table and a loose reading turned them into models (a row "New
    fine-tuning training on davinci-002" is the end of a feature, not of the model, and read loosely
    it yielded a model called `fine-tuning`):

      "gpt-5 , gpt-5-2025-08-07"                     every comma-separated item is an id
      "GPT-4o ( gpt-4o-2024-08-06 , ... )"           a display name, then the ids in parentheses
      "gpt-4-0125-preview (including a and b, ...)"  an id, plus the ids the parenthesis names
      "text-davinci-003 Historical price $20 / 1M"   an old model that quotes its price
    """
    cell = " ".join(cell.split())
    head, _, rest = cell.partition("(")
    paren = rest.rsplit(")", 1)[0] if rest else ""
    head = head.strip()

    priced = re.match(r"^(\S+)\s+Historical price\b", head)
    if priced and is_id(priced.group(1)):
        return [priced.group(1)]

    items = [t.strip("` ") for t in head.split(",") if t.strip("` ")]
    if items and all(is_id(t) for t in items):
        out = list(items)
        if paren.lower().startswith("including"):
            out += [t for t in (x.strip(".;:` ") for x in re.split(r"[,\s]+", paren)) if is_id(t)]
        return list(dict.fromkeys(out))

    if paren and head[:1].isupper() and len(head.split()) <= 3:
        named = [t.strip("` ") for t in paren.split(",")]
        if named and all(is_id(t) for t in named):
            return named
    return []


def col(head, *names):
    for i, h in enumerate(head):
        if any(h.lower().startswith(n) for n in names):
            return i
    return None


def main() -> int:
    today = dt.date.today()
    entries, skipped, shapes = [], [], []
    for t in html_tables.tables(sys.argv[1]):
        head = t[0]
        if not head or head[0].lower() != "shutdown date":
            continue
        i_m = col(head, "affected model")
        if i_m is None:
            continue
        i_st, i_rep = col(head, "status"), col(head, "recommended replacement", "listed replacement")
        i_n = col(head, "notice")
        past_table = i_st is None
        n0 = len(entries)
        for row in t[1:]:
            sd = iso(row[0])
            if sd is None or len(row) <= i_m:
                continue
            found = ids(row[i_m])
            if not found:
                skipped.append(row[i_m])
                continue
            d = dt.date.fromisoformat(sd)
            for mid in found:
                entries.append({
                    "id": mid, "provider": "OpenAI", "platform": "openai-api",
                    "shutdown": sd, "shutdown_as_published": row[0], "date_certainty": "firm",
                    "status": "retired" if d <= today else "scheduled",
                    "days_remaining": max(0, (d - today).days),
                    "replacement": row[i_rep] if i_rep is not None and i_rep < len(row) else "",
                    "announced": iso(row[i_n]) if i_n is not None and i_n < len(row) else None,
                    "page_status": row[i_st] if i_st is not None and i_st < len(row) else "Shutdown",
                    "section": "past" if past_table else "upcoming", "source": SOURCE,
                })
        shapes.append(("past deprecations" if past_table else "upcoming deprecations",
                       len(t) - 1, len(entries) - n0))

    json.dump({"source": SOURCE, "read_on": today.isoformat(), "models": entries},
              open(sys.argv[2], "w"), indent=1)
    print(f"{len(entries)} model ids -> {sys.argv[2]}")
    for name, rows, n in shapes:
        print(f"   {name:<22} {rows:>3} rows -> {n:>3} ids")
    if skipped:
        print(f"   {len(skipped)} rows named a feature, not a model id: {skipped[:4]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
