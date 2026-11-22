# model-retirements

![rebuild](https://github.com/pcbeingused333/model-retirements/actions/workflows/rebuild.yml/badge.svg)

Work in progress. A scheduled workflow rereads the four pages every six hours and rewrites the feed
only when something a consumer relies on changed, so `generated_at` is when the content last changed.
`data/status.json` says when the last check ran.

A machine-readable feed of the dates LLM providers stop serving their models, rebuilt from the
providers' own deprecation pages by parsers.

## Why this exists as a feed

Model retirement is the one failure in LLM integration code that arrives on a published
calendar, and it is still the most common one: across 1,488 upstream fixes merged in 369
repositories, defaults pointing at a retired model were fixed in 61 separate code bases, more
than any other single pattern.

The dates are useful far beyond one tool, so they live here on their own. A Go service, a
TypeScript CI job or a dashboard can read `feed.json` without installing a Python linter.

## Why it is parsed, not transcribed

The table this feed was first seeded from (`seed_feed.json`) was read by hand from the
providers' pages on 2026-10-19 and 2026-10-26. Re-read 25 days later against OpenAI's upcoming
deprecations alone, it had drifted: 6 models with the wrong recommended replacement (`gpt-5`
now goes to `gpt-6.1-sol`, not `gpt-5.6-sol`) and 41 models missing. A hand-copied table is a
constant in someone's source file, and these dates are not constant.

Today 353 of the feed's 360 entries were read from a provider page by a parser, with the date
they were read. The other 7 are aliases that no page names, kept from the seed and marked
`verified: false`.

## How to read a date

The providers do not all mean the same thing by a date, and flattening them is how a feed lies.
Every entry has `date_certainty`:

| Value | Meaning | Where it comes from |
| --- | --- | --- |
| `firm` | Already off, or a fixed shutdown date | OpenAI; the "Deprecated" sections of Gemini; Vertex's past and fixed dates |
| `announced` | A date the provider has given, which its own page labels tentative | Anthropic, for deprecated models |
| `not_earlier_than` | A floor. The model is promised until then and may be served longer | Anthropic "Not sooner than"; every live Gemini API date; Vertex "or later" |
| `unannounced` | The page says no date has been announced | all four |
| `unknown` | Not confirmed by any page today (`verified: false`) | the seed only |

Passing a `not_earlier_than` date retires nothing: such entries have `status: active` even when
the date is behind us. `scan.py` leaves them out unless you pass `--include-floors`.

## Where a date does not apply

Anthropic's page states that its dates are for the platforms Anthropic operates, and that Amazon
Bedrock and Google-managed Vertex AI set their own schedules. So the Claude entries are not
written with `anthropic.claude-...` or `us.anthropic.claude-...` ids, and OpenAI entries are not
written with `azure/`. A scanner that judged a Bedrock id by the Claude API's calendar would
report deadlines that are not real. The same model id can also have different dates on the
Gemini API and on Vertex AI (`gemini-2.5-flash`), so `scan.py` keeps every platform's entry for
an id and reports each one.

## Files

| File | What it does |
| --- | --- |
| `data/feed.json` | The feed: 360 entries across Anthropic, OpenAI, Gemini API and Vertex AI. |
| `parse_openai.py` | OpenAI's page, from its HTML tables: upcoming and past deprecations. |
| `parse_anthropic.py` | Anthropic's page, from its Markdown source: status table plus deprecation history, including aliases the prose names. |
| `parse_gemini.py` | Gemini API's page, from its Markdown source (the HTML is a JavaScript shell with no content). |
| `parse_vertex.py` | Vertex AI's page, from its HTML tables. |
| `merge_feed.py` | Builds `feed.json` from the four parsers and carries over only what no page confirms, marked unverified. |
| `rebuild.py`, `feedlib.py` | One rebuild from the live pages with the safety check, and the helpers that compute status from a date. |
| `drift.py` | Compares a held table against a freshly parsed page and lists every disagreement. |
| `scan.py` | Language-agnostic scan of a code base for ids in the feed. |
| `data/seed_feed.json`, `build_feed.py` | The original hand-maintained table and how it was exported. Kept so `drift.py` can still measure against it. |
| `tools/` | `html_tables.py` and `html_text.py`: parse a fetched page as data. Page content is untrusted and is never executed or followed as instructions. |

## Use

```console
# rebuild: save each page, parse it, merge
sh fetch_pages.sh pages
python parse_openai.py pages/openai.html data/openai_live.json
python parse_anthropic.py pages/anthropic.md data/anthropic_live.json
python parse_gemini.py pages/gemini.md data/gemini_live.json
python parse_vertex.py pages/vertex.html data/vertex_live.json
python merge_feed.py data/seed_feed.json data/feed.json data/openai_live.json data/anthropic_live.json data/gemini_live.json data/vertex_live.json

python scan.py data/feed.json ./src --config-only     # ids that look like configuration
python scan.py data/feed.json ./src --within-days=90  # only what is dated inside 90 days
python scan.py data/feed.json ./src --json            # machine-readable, one object per hit
python drift.py data/seed_feed.json data/openai_live.json OpenAI
```

Pages: `developers.openai.com/api/docs/deprecations`,
`platform.claude.com/docs/en/about-claude/model-deprecations.md`,
`aistudio.google.com/docs/deprecations.md` (what `ai.google.dev/gemini-api/docs/deprecations`
redirects to), and `docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/model-versions`.
`scan.py` exits 1 when it reports anything, so it can gate CI.

## Keeping it current

`.github/workflows/rebuild.yml` runs `rebuild.py` every six hours. Providers announce retirements
months ahead, so six hours is plenty; the point is to notice a change within the day.

- **It only writes when the content changed** (a date, a replacement, a certainty, an id). Fields that
  depend on today's date (`status`, `days_remaining`) are not stored: `feedlib.derive` computes them
  when the feed is read, so a quiet month produces no commits and nothing goes stale.
- **A rebuild that looks wrong fails the run instead of being committed.** If a provider drops to zero
  entries (its page changed shape and a parser read nothing) or loses more than a fifth of them, the
  feed is left alone and GitHub emails the owner about the failed run. `tests/test_rebuild.py` pins this.
- The daily first run also records the time of the check in `data/status.json`.

## Corrections

- **2026-11-22.** The OpenAI parser read any row of the table as a model if it contained something
  that looked like an id, so a row about the end of a *feature* ("New fine-tuning training on
  davinci-002") produced an entry for `fine-tuning` and gave `davinci-002` and `babbage-002` the
  wrong date and replacement. A row now counts as a model only in four exact shapes
  (`parse_openai.ids`), pinned by `tests/test_parse_openai.py`. The feed was rebuilt: one entry
  removed, two corrected. The same rebuild showed Vertex moving `gemini-3.6-flash` from 2026-11-19
  to 2027-01-28 two days after the first build.

## Honest limits, as of today

- **`scan.py` reads text, not syntax.** It cannot tell a model id that configures a request
  from one in a changelog, so every finding carries its context and `--config-only` keeps the
  ones that look like configuration. On a library that catalogues models (a router, a cost
  map) it reports thousands of hits that are not bugs. For Python, `llm-drift-lint` resolves
  the model through the AST and is the better tool.
- **The id guard prefers missing an alias to flagging a live model.** `gpt-5` does not match
  inside `gpt-5-codex`. An id the feed lists with a suffix is matched in full.
- **The parsers depend on each page's layout.** Anthropic and Gemini are read from Markdown
  and OpenAI and Vertex from HTML tables, by column name where the page has headers. A layout
  change makes a parser read zero rows or report rows it could not parse, and both are printed
  rather than guessed around. Rows whose date does not parse are left out: today that is
  `gemini-embedding-2` (empty cell) on Vertex and `gemini-3.5-flash` / `gemini-3.7-flash` (`N/A`)
  on the Gemini API.
- **Fine-tuned models** follow their base model's schedule, as OpenAI states, and are not
  enumerated.
- **Bedrock, Azure and Google-managed Anthropic ids are not covered.** Their schedules are
  their own, and this feed does not read them yet.
- OpenAI's page also offers `GET /v1/models` with a per-model `shutdown_date`. That needs an API
  key and would be the better source for a deployed service; this feed uses the public page.
