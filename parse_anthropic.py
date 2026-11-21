#!/usr/bin/env python3
"""Parse Anthropic's model-deprecations page (its Markdown source) into feed entries.

Two parts of the page are combined, because neither is complete alone:
  - "Model status" gives each current and recently retired model with its state and date;
  - "Deprecation history" gives the recommended replacement and the models that left the
    status table long ago. It also says, in prose, when a retirement covers an alias
    ("This retirement includes `claude-sonnet-4-5`, the same model's ID without a date"),
    which is collected here instead of being guessed.

What the page says about its own scope matters and is kept: its dates apply to the Claude
API and the platforms Anthropic operates. Amazon Bedrock and Google-managed Vertex AI set their
own schedules, so these entries are NOT valid for `anthropic.claude-...` Bedrock ids.

Certainty vocabulary:
    firm              already retired
    announced         a retirement date Anthropic has given (the page's own column header
                      calls it "tentative", so it is not promoted to firm)
    not_earlier_than  "Not sooner than <date>" on an active model
    unannounced       "To be announced"

Usage: parse_anthropic.py <anthropic.md> <out.json>
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys

SOURCE = "https://platform.claude.com/docs/en/about-claude/model-deprecations"
DATE = re.compile(r"([A-Z][a-z]+) (\d{1,2}), (\d{4})")
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June",
                                      "July", "August", "September", "October", "November",
                                      "December"], 1)}


def iso(cell: str):
    mo = DATE.search(cell)
    if not mo or mo.group(1) not in MONTHS:
        return None
    return f"{mo.group(3)}-{MONTHS[mo.group(1)]:02d}-{int(mo.group(2)):02d}"


def pipe_rows(block: list[str]):
    rows = []
    for line in block:
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue
        rows.append(cells)
    return rows


def sections(md: str):
    """(level, heading, body lines) for each ## and ### section."""
    out, cur = [], None
    for line in md.splitlines():
        mo = re.match(r"^(#{2,3})\s+(.*)$", line)
        if mo:
            if cur:
                out.append(cur)
            cur = (len(mo.group(1)), mo.group(2).strip(), [])
        elif cur:
            cur[2].append(line)
    if cur:
        out.append(cur)
    return out


def main() -> int:
    md = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    today = dt.date.today()
    models, conflicts = {}, []

    def entry(mid, shutdown, certainty, state, replacement="", announced=None, via=""):
        past = bool(shutdown) and dt.date.fromisoformat(shutdown) <= today
        floor = certainty == "not_earlier_than"
        # A "not sooner than" date is a floor: passing it retires nothing. Only a fixed date
        # that has passed, or the page's own "Retired" state, makes a model retired.
        retired = state == "Retired" or (past and not floor and bool(shutdown))
        return {
            "id": mid, "provider": "Anthropic", "platform": "claude-api",
            "shutdown": shutdown, "date_certainty": certainty,
            "status": "retired" if retired else "active" if (floor or not shutdown) else "scheduled",
            "days_remaining": (max(0, (dt.date.fromisoformat(shutdown) - today).days)
                               if shutdown and not retired else 0),
            "replacement": replacement, "announced": announced, "page_state": state,
            "via": via, "source": SOURCE,
        }

    secs = sections(md)
    for level, heading, body in secs:
        if heading != "Model status":
            continue
        for cells in pipe_rows(body)[1:]:
            if len(cells) < 4:
                continue
            mid, state, dep, ret = (c.strip("` ") for c in cells[:4])
            if ret.lower().startswith("not sooner than"):
                sd, cert = iso(ret), "not_earlier_than"
            elif ret.lower().startswith("to be announced"):
                sd, cert = None, "unannounced"
            else:
                sd = iso(ret)
                cert = "firm" if state == "Retired" else "announced"
            models[mid] = entry(mid, sd, cert, state, announced=iso(dep), via="status table")

    for level, heading, body in secs:
        if not re.match(r"^\d{4}-\d{2}-\d{2}:", heading):
            continue
        text = "\n".join(body)
        announced = heading[:10]
        for cells in pipe_rows(body)[1:]:
            if len(cells) < 3:
                continue
            date = iso(cells[0])
            repl = " or ".join(re.findall(r"`([^`]+)`", cells[2]))
            for mid in re.findall(r"`([^`]+)`", cells[1]):
                if mid in models:
                    if models[mid]["shutdown"] and date and models[mid]["shutdown"] != date:
                        conflicts.append((mid, models[mid]["shutdown"], date))
                    models[mid]["replacement"] = models[mid]["replacement"] or repl
                    models[mid]["announced"] = models[mid]["announced"] or announced
                else:
                    e = entry(mid, date, "firm" if date and date <= today.isoformat()
                              else "announced", "Retired" if date and date <= today.isoformat()
                              else "Deprecated", repl, announced, "deprecation history")
                    models[mid] = e
                for alias in re.findall(r"includes\s+`([^`]+)`", text):
                    if alias not in models:
                        a = dict(models[mid])
                        a.update(id=alias, via=f"alias of {mid}, stated in the page's prose")
                        models[alias] = a

    out = sorted(models.values(), key=lambda e: (e["shutdown"] or "9999", e["id"]))
    json.dump({"source": SOURCE, "read_on": today.isoformat(), "models": out},
              open(sys.argv[2], "w"), indent=1)
    import collections
    print(f"{len(out)} models -> {sys.argv[2]}")
    for k, n in sorted(collections.Counter((e["status"], e["date_certainty"]) for e in out).items()):
        print(f"   {n:>3}  {k[0]:<10} {k[1]}")
    print("   by origin:", dict(collections.Counter(e["via"].split(",")[0] for e in out)))
    if conflicts:
        print(f"\n!! {len(conflicts)} id(s) whose status-table date and history date disagree:")
        for c in conflicts:
            print("   ", c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
