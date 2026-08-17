# Changelog

Pre-1.0: minor versions may change behavior; patch versions are fixes only.

## 0.2.0 (2026-08-17)

First public release (GitHub + PyPI), after an adversarial review pass
(security, parsing correctness, packaging and claims).

Matching and parsing:

- Cited co-author surnames now disambiguate same-author-same-year works, and
  co-authors a citation does not name count against a candidate file.
- A match resting on first author and year alone, on a year-suffix fallback,
  or on a tie carries an explicit caution in the report; lettered same-year
  works (2020a vs 2020b) are never cross-matched.
- Page spans ("pp. 2011-2014"), year ranges, and stat parentheticals no longer
  parse as citations; possessive narrative citations (Bandura's, 1977) key
  correctly; multi-author narrative lists key on the first author; name
  particles (Van der Berg) key consistently in both citation forms; diacritic
  surnames become misses instead of truncated wrong keys.
- Reference-list parsing survives "in press" entries, wrapped location lines,
  and markdown heading markers from pandoc-converted manuscripts.
- Oversized paragraphs (two-column pdftotext output) are windowed so retrieval
  always ranks multiple passages; retrieval queries drop citation markers and
  bare years so a source's own reference list stops outranking its body.

Confidentiality and robustness:

- The local Ollama call ignores proxy environment and system proxy settings;
  on proxied machines nothing routes off localhost.
- `--map` targets are validated (must exist inside the bank folder); malformed
  map files fail fast with a clean error.
- The Anthropic API key is validated without ever echoing it; exception text
  destined for reports is redacted.
- pdftotext runs with a timeout, closed stdin, and a resolved binary path;
  unreadable matched sources are reported per pair instead of crashing runs.
- Reasoning models are supported via a request-mode fallback chain (strict
  JSON, thinking disabled, bare), cached per run.
- Quoted report content is markdown-escaped; model text is
  whitespace-flattened so it cannot forge report structure.

Reporting:

- `--model none` produces an honest "not assessed" report with all retrieved
  passages; `--max-pairs` overflow is counted and disclosed; skipped bank
  files are listed on stderr; unverifiable works are counted uniquely.

## 0.1.0 (2026-08-15)

Initial working version: APA extraction, bank matching, BM25 retrieval,
graded verdicts with quoted evidence, Ollama/Anthropic/none providers,
risk-ranked markdown report. Never published.
