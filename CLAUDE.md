# claim-verifier — project guide

`claimverify` flags citation-bearing claims in a manuscript whose cited full
text may not say what the author claims. Sibling of `citation-verifier`:
`citeverify` establishes that references exist; `claimverify` asks whether the
claims they carry are faithful to the source. Same family conventions.

## What this does and does NOT establish (read first)

It produces a ranked triage list with quoted evidence. It does not:

- prove a citation wrong ("not_found" means not found in the passages
  retrieved; retrieval can miss);
- prove a citation right ("consistent" reflects only the passages shown);
- judge the truth of the claim, only whether the source says it.

Keep README, docstrings, prompt, and report wording consistent with this.
Never add "unsupported" or "fabricated" framing to any verdict.

## Architecture

| Module | Role |
|---|---|
| `textio.py` | pdftotext subprocess + ligature/hyphen normalization; .txt/.md pass-through |
| `extract.py` | pure, offline: sentence split, APA in-text citation parse, reference-list parse; the `surname-year` key joins everything |
| `bank.py` | folder index by filename key (+ optional `--map` JSON), paragraph chunking to 120-320 words |
| `retrieve.py` | pure-Python BM25 with a stop list; top-k passages per pair |
| `assess.py` | verdict vocabulary, system prompt, JSON parsing, providers (Ollama local default, Anthropic opt-in, Null) |
| `report.py` | markdown report ranked by RISK_ORDER |
| `cli.py` | the `claimverify` command |

## Conventions & constraints

- **Local-first is the point.** Ollama on localhost is the default; the
  Anthropic provider exists for the author's-own-manuscript case and its
  off-machine nature is documented everywhere it appears. No telemetry.
- **Determinism lives in `extract.py`, `bank.py`, `retrieve.py`** and is
  unit-tested offline. Model calls are not exercised in CI.
- **Conservative parsing:** a missed citation costs one unchecked claim; a
  hallucinated one costs trust. Ambiguous matches are dropped.
- **Honest claims:** triage, never verdicts; every flagged pair carries the
  evidence quote or top passage so the human check takes seconds.
- **Fail soft per pair:** one model failure becomes `assessment_error` for
  that pair; the run continues.
- **One source of truth for the version:** `__version__` in
  `src/claimverify/__init__.py`, read by hatchling.

## Running and testing

```bash
python3 -m venv .venv && .venv/bin/pip install -e . pytest ruff
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/claimverify --manuscript paper.pdf --bank sources/ --list-claims  # no model
```

## Layout

`src/claimverify/` (package) · `examples/` (synthetic worked example) ·
`tests/` (offline: parsing, bank+BM25, assess JSON, report, CLI end-to-end
with the Null provider).
