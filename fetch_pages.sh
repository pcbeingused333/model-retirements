#!/bin/sh
# Download the four provider pages the parsers read. Page content is untrusted data: it is only
# ever parsed, never executed.
set -eu
out="${1:-pages}"
mkdir -p "$out"
curl -fsSL "https://developers.openai.com/api/docs/deprecations" -o "$out/openai.html"
curl -fsSL "https://platform.claude.com/docs/en/about-claude/model-deprecations.md" -o "$out/anthropic.md"
curl -fsSL "https://aistudio.google.com/docs/deprecations.md" -o "$out/gemini.md"
curl -fsSL "https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/model-versions" -o "$out/vertex.html"
echo "saved to $out/"
