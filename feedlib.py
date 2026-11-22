"""Helpers shared by the scripts that read or rebuild the feed."""
from __future__ import annotations

import datetime as dt


def derive(entry: dict, today: dt.date | None = None) -> tuple[str, int]:
    """(status, days remaining) of an entry, computed from its date.

    These two values depend on today's date, so they are NOT stored in the feed: a feed that is
    rewritten only when its content changes would keep yesterday's answers for weeks. A "not earlier
    than" floor and an unannounced date are never a shutdown, so those models are `active`.
    """
    today = today or dt.date.today()
    shutdown = entry.get("shutdown")
    if not shutdown or entry.get("date_certainty") in ("not_earlier_than", "unannounced"):
        return "active", 0
    date = dt.date.fromisoformat(shutdown)
    if date <= today:
        return "retired", 0
    return "scheduled", (date - today).days


def with_derived(feed: dict, today: dt.date | None = None) -> dict:
    """The same feed with `status` and `days_remaining` filled in on every entry."""
    for entry in feed["models"]:
        entry["status"], entry["days_remaining"] = derive(entry, today)
    return feed


def substance(feed: dict) -> dict:
    """What a consumer relies on, without anything that changes just because time passed."""
    return {
        (e["platform"], e["id"]): (e.get("shutdown"), e.get("date_certainty"), e.get("replacement", ""))
        for e in feed["models"]
    }


def changes(old: dict, new: dict) -> list[str]:
    """Human-readable differences between two feeds, empty when nothing a consumer relies on moved."""
    a, b = substance(old), substance(new)
    out = []
    for key in sorted(set(b) - set(a)):
        out.append(f"added    {key[0]:<10} {key[1]}  {b[key][0]} ({b[key][1]})")
    for key in sorted(set(a) - set(b)):
        out.append(f"removed  {key[0]:<10} {key[1]}  (was {a[key][0]})")
    for key in sorted(set(a) & set(b)):
        if a[key] != b[key]:
            out.append(f"changed  {key[0]:<10} {key[1]}  {a[key]} -> {b[key]}")
    return out
