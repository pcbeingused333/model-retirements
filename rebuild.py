#!/usr/bin/env python3
"""Rebuild the feed from the providers' pages and report whether anything a consumer relies on moved.

Exit code:  0  nothing changed (the committed feed already says the same);
           10  the feed changed: the new files are written into data/ and the changes are printed;
            1  something is wrong and nothing was written.

"Something is wrong" is the point of the check. A provider that restyles its page makes a parser
read zero rows, and a feed rebuilt blindly would then silently lose that provider. So a provider
that drops to nothing, or loses more than a fifth of its entries, fails the run instead.

The feed is only rewritten when its content changes. Fields that merely depend on today's date are not
stored (see feedlib.derive), so a quiet week produces no commit.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import feedlib  # noqa: E402

DATA = HERE / "data"
PARSERS = (
    ("parse_openai.py", "openai.html", "openai_live.json"),
    ("parse_anthropic.py", "anthropic.md", "anthropic_live.json"),
    ("parse_gemini.py", "gemini.md", "gemini_live.json"),
    ("parse_vertex.py", "vertex.html", "vertex_live.json"),
)
MAX_LOSS = 0.2


def run(*cmd: object) -> None:
    subprocess.run([str(c) for c in cmd], check=True, cwd=HERE)


def gate(old: dict, new: dict) -> list[str]:
    """Reasons not to trust the new feed."""
    problems = []
    before = {}
    after = {}
    for e in old["models"]:
        before[e["provider"]] = before.get(e["provider"], 0) + 1
    for e in new["models"]:
        after[e["provider"]] = after.get(e["provider"], 0) + 1
    for provider, n_old in before.items():
        n_new = after.get(provider, 0)
        if n_new == 0:
            problems.append(f"{provider}: no entries at all (had {n_old}); its page probably changed shape")
        elif n_new < (1 - MAX_LOSS) * n_old:
            problems.append(f"{provider}: {n_new} entries, down from {n_old}")
    return problems


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="retirements-"))
    try:
        pages = work / "pages"
        run("sh", "fetch_pages.sh", pages)
        for script, page, out in PARSERS:
            run(sys.executable, script, pages / page, work / out)
        run(
            sys.executable, "merge_feed.py", DATA / "seed_feed.json", work / "feed.json",
            *(work / out for _, _, out in PARSERS),
        )
        old = json.loads((DATA / "feed.json").read_text(encoding="utf-8"))
        new = json.loads((work / "feed.json").read_text(encoding="utf-8"))

        problems = gate(old, new)
        if problems:
            print("\nNOT WRITTEN, the rebuilt feed looks wrong:", *problems, sep="\n  ", file=sys.stderr)
            return 1

        (DATA / "status.json").write_text(
            json.dumps({"checked_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n",
            encoding="utf-8",
        )
        moved = feedlib.changes(old, new)
        if not moved:
            print("\nNo change: the providers' pages say what the feed already says.")
            return 0
        print(f"\n{len(moved)} change(s):", *moved[:60], sep="\n  ")
        if len(moved) > 60:
            print(f"  ... and {len(moved) - 60} more")
        shutil.copy(work / "feed.json", DATA / "feed.json")
        for _, _, out in PARSERS:
            shutil.copy(work / out, DATA / out)
        return 10
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
