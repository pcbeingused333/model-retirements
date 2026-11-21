#!/usr/bin/env python3
"""Scan a code base for model ids their provider has retired or is about to retire.

This is the language-agnostic consumer of feed.json. It reads text, not syntax trees, so it
works on Go, TypeScript, C#, Ruby, YAML and Dockerfiles alike. The trade-off is honest and
worth stating plainly: a text scanner cannot tell a model id that configures a request from
one that appears in a changelog. So every finding carries the context it was found in, and
`--config-only` keeps the ones that look like they set a model rather than mention one. For
Python specifically, llm-drift-lint resolves the model through the AST and is the better tool.

Exit code 1 if anything is reported, so it can gate CI.

Usage: scan.py <feed.json> <path> [--config-only] [--within-days=N] [--include-floors] [--json]
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys

SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", ".venv", "venv",
             "target", "__pycache__", ".next", ".tox", "bin", "obj"}
SKIP_EXT = {".lock", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".pdf", ".zip",
            ".gz", ".tar", ".woff", ".woff2", ".ttf", ".mp4", ".so", ".dll", ".dylib",
            ".wasm", ".bin", ".pyc", ".class", ".jar"}
SKIP_FILES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "uv.lock",
              "go.sum", "Cargo.lock", "Gemfile.lock", "composer.lock"}

# A line that configures a model, rather than one that merely names it.
CONFIG = re.compile(
    r"(model|deployment|engine|llm|checkpoint)[\"'\]]?\s*(=|:|=>|:=|\?\?|\|\|)"
    r"|(default|DEFAULT|fallback|FALLBACK)"
    r"|getenv|environ|os\.Getenv|process\.env|ENV\[",
)
COMMENT = re.compile(r"^\s*(#|//|\*|<!--|--)")


def id_pattern(ids):
    """One regex over every id, longest first so `gpt-4.1-nano-2025-04-14` wins over `gpt-4.1-nano`.

    The trailing guard is what keeps a retired id from matching a live successor: `gpt-4` must
    not fire on `gpt-4o` (a letter follows), `gpt-5` must not fire on `gpt-5.6-sol` (a dot and a
    digit) or on `gpt-5-codex` (a different, live model), and `claude-opus-4` must not fire on
    `claude-opus-4-8`. Any id the feed knows with a suffix is listed in full and wins by length.
    A dated snapshot like `claude-opus-4@20250514` IS the same model, so `@` is allowed through.
    The trade is deliberate: a missed alias is a false negative, a flagged live model is a
    false positive, and the second is the one that loses a user's trust.
    """
    alts = "|".join(re.escape(i) for i in sorted(ids, key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z0-9._/-])({alts})(?![A-Za-z0-9]|[-_.][A-Za-z0-9])")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    feed_path, target = args[0], args[1]
    config_only = "--config-only" in flags
    include_floors = "--include-floors" in flags
    as_json = "--json" in flags or "--format=json" in flags
    within = next((int(f.split("=")[1]) for f in flags if f.startswith("--within-days=")), None)

    feed = json.load(open(feed_path))
    today = dt.date.today()

    # One id can be on several platforms with different dates (gemini-2.5-flash on the Gemini
    # API and on Vertex AI), so an id keeps every entry rather than the last one written.
    by_id = {}
    for e in feed["models"]:
        if not e.get("shutdown"):
            continue
        # "Not sooner than" is a promise of availability, not a deadline: reporting every
        # current model for it would bury the findings that matter.
        if e.get("date_certainty") == "not_earlier_than" and not include_floors:
            continue
        if within is not None and e["status"] == "scheduled" and e["days_remaining"] > within:
            continue
        for spelling in [e["id"]] + e.get("also_written_as", []):
            by_id.setdefault(spelling, []).append(e)
    if not by_id:
        print("feed has no dated entries to scan for")
        return 0
    pat = id_pattern(by_id)

    findings = []
    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if fn in SKIP_FILES or os.path.splitext(fn)[1].lower() in SKIP_EXT:
                continue
            path = os.path.join(root, fn)
            try:
                if os.path.getsize(path) > 2_000_000:
                    continue
                text = open(path, encoding="utf-8", errors="strict").read()
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                for mo in pat.finditer(line):
                    es = sorted(by_id[mo.group(1)], key=lambda x: x["shutdown"])
                    e = es[0]
                    ctx = ("comment" if COMMENT.match(line)
                           else "config" if CONFIG.search(line) else "mention")
                    if config_only and ctx != "config":
                        continue
                    findings.append(dict(
                        file=os.path.relpath(path, target), line=lineno, context=ctx,
                        found=mo.group(1), model=e["id"], provider=e["provider"],
                        platform=e["platform"], shutdown=e["shutdown"], status=e["status"],
                        days_remaining=e["days_remaining"], replacement=e["replacement"],
                        date_certainty=e.get("date_certainty", "firm"),
                        verified=all(x.get("verified", True) for x in es),
                        platforms=[dict(platform=x["platform"], shutdown=x["shutdown"],
                                        status=x["status"],
                                        date_certainty=x.get("date_certainty", "firm"),
                                        replacement=x["replacement"]) for x in es],
                        source_line=line.strip()[:160]))

    if as_json:
        json.dump({"generated_at": today.isoformat(), "feed_generated_at": feed["generated_at"],
                   "findings": findings}, sys.stdout, indent=1)
        print()
    else:
        if not findings:
            print(f"No retired or expiring model ids found in {target}")
            return 0
        retired = [f for f in findings if f["status"] == "retired"]
        print(f"{len(findings)} finding(s) in {target}: "
              f"{len(retired)} already retired, {len(findings) - len(retired)} scheduled\n")
        for f in sorted(findings, key=lambda f: (f["shutdown"], f["file"], f["line"])):
            def when(x):
                floor = " or later" if x["date_certainty"] == "not_earlier_than" else ""
                return (f"RETIRED {x['shutdown']}" if x["status"] == "retired"
                        else f"{x['shutdown']}{floor}")
            print(f"  {f['file']}:{f['line']}  [{f['context']}]")
            if len(f["platforms"]) > 1:
                print(f"     {f['found']}  depends on where it runs:")
                for x in f["platforms"]:
                    print(f"        {x['platform']:<11} {when(x)}  -> {x['replacement']}")
            else:
                print(f"     {f['found']}  ({f['provider']}, {when(f['platforms'][0])})"
                      f"  -> {f['replacement']}")
            print(f"     | {f['source_line']}")
        print(f"\nFeed read the providers' pages on: "
              + ", ".join(f"{p} {s['checked']}" for p, s in sorted(feed["sources"].items())))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
