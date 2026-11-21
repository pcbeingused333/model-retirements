#!/usr/bin/env python3
"""Parse Google's Gemini API deprecations page (its Markdown source) into feed entries.

The HTML page is a JavaScript shell with no content in it; the same page is served as
Markdown at <page>.md, which is the faithful and parseable source. The page says how to read
its own dates, and the parser keeps that meaning:

    "The shutdown dates listed in the table indicate the earliest possible dates on which a
     model might be retired."

so a date in a live table is a floor (`not_earlier_than`), "No shutdown date announced" has no
date to record (`unannounced`), and a row in a "Deprecated" section describes something that
is already off (`firm`, status retired).

Usage: parse_gemini.py <gemini.md> <out.json>
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys

SOURCE = "https://ai.google.dev/gemini-api/docs/deprecations"
DATE = re.compile(r"^([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})$")
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June",
                                      "July", "August", "September", "October", "November",
                                      "December"], 1)}


LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def plain(cell: str) -> str:
    """A markdown link [text](url) is its text."""
    return LINK.sub(r"\1", cell)


def replacement_ids(cell: str) -> tuple[str, str]:
    """(ids, note): the ids named before any parenthesis, and the whole cell as prose.

    A replacement cell can read "`gemini-3.5-flash-lite` (`gemini-2.5-flash` is no longer ...)":
    the recommendation is the id before the parenthesis, the rest is commentary.
    """
    cell = plain(cell)
    head = cell.split("(")[0]
    ids = re.findall(r"`([^`]+)`", head) or ([head.strip()] if head.strip() else [])
    note = cell.replace("`", "").strip()
    return " or ".join(ids), (note if note != " or ".join(ids) else "")


def parse_date(cell: str):
    cell = cell.strip()
    if re.match(r"(?i)^no (shutdown )?date", cell) or cell == "":
        return None, "unannounced"
    mo = DATE.match(cell)
    if not mo or mo.group(1) not in MONTHS:
        return None, "unparsed"
    return f"{mo.group(3)}-{MONTHS[mo.group(1)]:02d}-{int(mo.group(2)):02d}", "date"


def tables(md: str):
    """Yield (section heading, header cells, rows) for each {% table %} block."""
    heading = ""
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        mo = re.match(r"^#{1,4}\s+(.*?)(\s*\{%.*)?$", line)
        if mo:
            heading = mo.group(1).strip()
        if line.strip().startswith("{% table"):
            j, block = i + 1, []
            while j < len(lines) and not lines[j].strip().startswith("{% /table"):
                block.append(lines[j])
                j += 1
            groups, cur = [], []
            for b in block:
                if b.strip() == "---":
                    groups.append(cur)
                    cur = []
                elif b.lstrip().startswith("*"):
                    cur.append(b.lstrip()[1:].strip())
            groups.append(cur)
            groups = [g for g in groups if g]
            if groups:
                yield heading, groups[0], groups[1:]
            i = j
        i += 1


def main() -> int:
    md = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    today = dt.date.today()
    entries, unparsed, summary = [], [], []
    for heading, head, rows in tables(md):
        low = [h.lower() for h in head]
        i_id = next((k for k, h in enumerate(low) if h in ("model", "agent")), None)
        i_sd = next((k for k, h in enumerate(low) if "shutdown" in h), None)
        i_rel = next((k for k, h in enumerate(low) if "release" in h), None)
        i_rep = next((k for k, h in enumerate(low) if "replacement" in h), None)
        if i_id is None or i_sd is None:
            continue
        already_off = "deprecated" in heading.lower()
        n0 = len(entries)
        for row in rows:
            row = [plain(c) for c in row]
            if len(row) <= max(i_id, i_sd):
                continue
            iso, kind = parse_date(row[i_sd])
            if kind == "unparsed":
                unparsed.append((row[i_id], row[i_sd]))
                continue
            repl, note = (replacement_ids(row[i_rep])
                          if i_rep is not None and i_rep < len(row) else ("", ""))
            for mid in [m.strip("` ") for m in re.split(r"[,\n]", row[i_id]) if m.strip("` ")]:
                # Rows in a live table carry the page's "earliest possible" dates, which stay
                # floors even once passed. Only the "Deprecated" sections are already off.
                certainty = ("unannounced" if kind == "unannounced"
                             else "firm" if already_off else "not_earlier_than")
                retired = already_off and bool(iso)
                entries.append({
                    "id": mid, "provider": "Google", "platform": "gemini-api",
                    "shutdown": iso, "shutdown_as_published": row[i_sd],
                    "date_certainty": certainty,
                    "status": "retired" if retired else "active",
                    "days_remaining": 0,
                    "replacement": repl, "replacement_note": note,
                    "released": row[i_rel] if i_rel is not None and i_rel < len(row) else "",
                    "section": heading, "source": SOURCE,
                })
        summary.append((heading, len(entries) - n0))

    json.dump({"source": SOURCE, "read_on": today.isoformat(), "models": entries},
              open(sys.argv[2], "w"), indent=1)
    print(f"{len(entries)} entries from {len(summary)} tables -> {sys.argv[2]}")
    for h, n in summary:
        print(f"   {n:>3}  {h}")
    if unparsed:
        print(f"\n!! {len(unparsed)} rows whose date did not parse (kept out, not guessed):")
        for mid, cell in unparsed[:15]:
            print(f"   {mid!r}: {cell!r}")
    import collections
    print("\nby status / certainty:")
    for k, n in sorted(collections.Counter((e["status"], e["date_certainty"]) for e in entries).items()):
        print(f"   {n:>3}  {k[0]:<10} {k[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
