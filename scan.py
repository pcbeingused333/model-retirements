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
                                  [--kinds=source,example,test,docs,catalogue | --all]
"""
from __future__ import annotations

import collections
import datetime as dt
import json

import os
from pathlib import Path
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feedlib  # noqa: E402
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


# Libraries write `google/gemini-2.0-flash-001` or `vertexai/text-bison`: the provider is part of the
# string and the model is the id after it. Any other `/` before an id is a path (`docs/gpt-4.md`).
PROVIDER_PREFIXES = ("openai", "azure", "google", "vertexai", "vertex_ai", "gemini", "anthropic",
                     "bedrock", "models")


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
    prefixed = "".join(rf"|(?<=(?<![A-Za-z0-9._/-]){p}/)" for p in PROVIDER_PREFIXES)
    return re.compile(rf"(?:(?<![A-Za-z0-9._/-]){prefixed})({alts})(?![A-Za-z0-9]|[-_.][A-Za-z0-9])")


KEY = r"(?:model|deployment|engine|llm|checkpoint)"
# The id is the VALUE of a model key: `model="x"`, `model: "x"`, `OpenAI(model="x")`.
ASSIGNED = re.compile(KEY + r"""[\w.]*["']?\s*(?:=>|:=|=|:)\s*(?:[\w.]+\s*\()?\s*["'`]$""", re.I)
# A whole line that is a key and a value (YAML, TOML, .env, a dict entry on its own line).
KEY_VALUE_LINE = re.compile(
    r"""^\s*[-\s]*[\w.\-"']*""" + KEY + r"""[\w.\-"']*\s*[:=]\s*["'`]?[^\s"'`#,)]+["'`]?\s*,?\s*(?:#.*)?$""", re.I)
FALLBACK = re.compile(r"(getenv|environ|process\.env|ENV\[|default|fallback)", re.I)


def context_of(line: str, start: int) -> str:
    """`comment`, `config` or `mention` for a model id found at `start` in `line`.

    `config` means the id is the value of a model setting. An id inside a sentence, a docstring
    ("e.g., "gemini-2.0-flash""), a log message or a printed example is a `mention`: in a sample of
    40 hits, 9 were that kind and none of the 30 real ones was misread this way.
    """
    if COMMENT.match(line):
        return "comment"
    if ASSIGNED.search(line[:start]) or KEY_VALUE_LINE.match(line):
        return "config"
    quoted = start > 0 and line[start - 1] in "'\"`"
    if quoted and FALLBACK.search(line):
        return "config"
    return "mention"


TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "e2e", "testdata", "fixtures", "__mocks__",
             "mocks", "cypress", "playwright"}
DOC_DIRS = {"docs", "doc", "documentation", "website", "blog", "wiki", "site"}
EXAMPLE_DIRS = {"examples", "example", "samples", "sample", "demo", "demos", "cookbook", "notebooks"}
DOC_EXT = {".md", ".mdx", ".rst", ".txt", ".adoc", ".ipynb"}
TEST_NAME = re.compile(r"(^test_|^conftest\.py$|(_test|\.test|\.spec|_spec)\.[a-z]+$)", re.I)
CATALOGUE_NAME = re.compile(
    r"(model[_-]?(prices?|cost|list|catalog|registry|map)|pricing|(^|[_-])prices?([_-]|\.)|catalog|cost[_-]?map"
    r"|^models\.(json|ya?ml)$)", re.I)
# A file that names this many distinct retired or retiring models is a list of models, not code that
# uses one. A cost map, a provider registry or a router's table of every model it supports.
CATALOGUE_DISTINCT = 12
SHOWN_BY_DEFAULT = ("source", "example")


def classify(relpath: str, distinct_models: int) -> str:
    """What kind of file a finding is in: `test`, `docs`, `catalogue`, `example` or `source`.

    Most of what a text scan finds is in tests and documentation, which mention models without
    being configured by them, and in files that merely list every model a library knows. Reporting
    those as findings is how a scan of a model router returned 6,893 hits. They are kept, labelled,
    and left out of the default report, which says how many it left out.
    """
    path = Path(relpath)
    folders = {p.lower() for p in path.parts[:-1]}
    name = path.name
    if folders & TEST_DIRS or TEST_NAME.search(name):
        return "test"
    if path.suffix.lower() in DOC_EXT or folders & DOC_DIRS:
        return "docs"
    if distinct_models >= CATALOGUE_DISTINCT or CATALOGUE_NAME.search(name):
        return "catalogue"
    if folders & EXAMPLE_DIRS:
        return "example"
    return "source"


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    feed_path, target = args[0], args[1]
    config_only = "--config-only" in flags
    include_floors = "--include-floors" in flags
    kinds = next((f.split("=", 1)[1].split(",") for f in flags if f.startswith("--kinds=")), None)
    if "--all" in flags:
        kinds = ["source", "example", "test", "docs", "catalogue"]
    kinds = kinds or list(SHOWN_BY_DEFAULT)
    as_json = "--json" in flags or "--format=json" in flags
    within = next((int(f.split("=")[1]) for f in flags if f.startswith("--within-days=")), None)

    feed = feedlib.with_derived(json.load(open(feed_path)))
    today = dt.date.today()

    # One id can be on several platforms with different dates (gemini-2.5-flash on the Gemini
    # API and on Vertex AI), so an id keeps every entry rather than the last one written.
    by_id = {}
    for e in feed["models"]:
        if not e.get("shutdown"):
            continue
        # A "not sooner than" date is a promise of availability, not a deadline, so on its own it is
        # never reported (every current model has one). It is kept here so that it can be SHOWN beside
        # a decided date for the same id on another platform: gemini-2.5-flash is retired on Vertex AI
        # but only "not before 2026-12-01" on the Gemini API, and showing just the first misleads.
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
            file_findings = []
            for lineno, line in enumerate(text.splitlines(), 1):
                for mo in pat.finditer(line):
                    es = sorted(by_id[mo.group(1)], key=lambda x: x["shutdown"])
                    decided = [x for x in es if x.get("date_certainty") != "not_earlier_than"]
                    if not decided and not include_floors:
                        continue
                    e = (decided or es)[0]
                    ctx = context_of(line, mo.start())
                    if config_only and ctx != "config":
                        continue
                    file_findings.append(dict(
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
            if file_findings:
                kind = classify(file_findings[0]["file"], len({f["model"] for f in file_findings}))
                for f in file_findings:
                    f["kind"] = kind
                findings.extend(file_findings)

    hidden = collections.Counter(f["kind"] for f in findings if f["kind"] not in kinds)
    findings = [f for f in findings if f["kind"] in kinds]

    if as_json:
        json.dump({"generated_at": today.isoformat(), "feed_generated_at": feed["generated_at"],
                   "kinds_shown": kinds, "hidden": dict(hidden), "findings": findings}, sys.stdout, indent=1)
        print()
    else:
        left_out = (f"  Left out: " + ", ".join(f"{n} in {k}" for k, n in sorted(hidden.items()))
                    + ". See them with --all.") if hidden else ""
        if not findings:
            print(f"No retired or expiring model ids found in {', '.join(kinds)} files of {target}.{left_out}")
            return 0
        retired = [f for f in findings if f["status"] == "retired"]
        print(f"{len(findings)} finding(s) in {target}: "
              f"{len(retired)} already retired, {len(findings) - len(retired)} scheduled.{left_out}\n")
        for f in sorted(findings, key=lambda f: (f["shutdown"], f["file"], f["line"])):
            def when(x):
                floor = " or later" if x["date_certainty"] == "not_earlier_than" else ""
                return (f"RETIRED {x['shutdown']}" if x["status"] == "retired"
                        else f"{x['shutdown']}{floor}")
            print(f"  {f['file']}:{f['line']}  [{f['context']}, {f['kind']}]")
            if len(f["platforms"]) > 1:
                print(f"     {f['found']}  depends on where it runs:")
                for x in f["platforms"]:
                    print(f"        {x['platform']:<11} {when(x)}  -> {x['replacement']}")
            else:
                print(f"     {f['found']}  ({f['provider']}, {when(f['platforms'][0])})"
                      f"  -> {f['replacement']}")
            print(f"     | {f['source_line']}")
        print(f"\nFeed read the providers' pages on: "
              + ", ".join(f"{p} {s.get('read_on') or s.get('checked')}" for p, s in sorted(feed["sources"].items())))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
