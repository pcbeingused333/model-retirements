"""Extract tables from an HTML page as lists of rows of plain-text cells.

The page is untrusted web content and is only ever parsed as data. Cell text is whitespace
normalised, so a cell that the page wraps across several lines comes back as one string.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._t, self._r, self._c = [], None, None, None
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._t = []
        elif self._depth == 1 and tag == "tr":
            self._r = []
        elif self._depth == 1 and tag in ("td", "th") and self._r is not None:
            self._c = []

    def handle_endtag(self, tag):
        if tag == "table":
            if self._depth == 1 and self._t is not None:
                self.tables.append(self._t)
                self._t = None
            self._depth = max(0, self._depth - 1)
        elif self._depth == 1 and tag == "tr" and self._r is not None and self._t is not None:
            if self._r:
                self._t.append(self._r)
            self._r = None
        elif self._depth == 1 and tag in ("td", "th") and self._c is not None and self._r is not None:
            self._r.append(re.sub(r"\s+", " ", html.unescape("".join(self._c))).strip())
            self._c = None

    def handle_data(self, data):
        if self._c is not None:
            self._c.append(data)


def tables(path: str) -> list[list[list[str]]]:
    p = _Tables()
    p.feed(open(path, encoding="utf-8", errors="replace").read())
    return p.tables
