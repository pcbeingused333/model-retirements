#!/usr/bin/env python3
"""Strip an HTML page to text. Input is untrusted web content: it is parsed as data only."""
import html, re, sys
raw = open(sys.argv[1], encoding="utf-8", errors="replace").read()
raw = re.sub(r"(?is)<(script|style|svg|noscript).*?</\1>", " ", raw)
raw = re.sub(r"(?i)</(tr|p|div|li|h[1-6]|table)>", "\n", raw)
raw = re.sub(r"(?i)</t[dh]>", " | ", raw)
txt = html.unescape(re.sub(r"(?s)<[^>]+>", " ", raw))
txt = re.sub(r"[ \t ]+", " ", txt)
print("\n".join(l.strip() for l in txt.splitlines() if l.strip()))
