# claim-verifier

Flag citation-bearing claims in a manuscript whose cited full text may not say
what the author claims. `claimverify` reads a manuscript, finds every sentence
that carries an APA in-text citation, retrieves the most relevant passages from
a folder of cited-source full texts you supply, and asks a language model (a
local one by default) whether each passage matches what the sentence attributes
to that source. The output is a ranked markdown report a human works through.

It is a triage aid, not a judge. The most recent meta-analysis of quotation
errors in medicine estimates that roughly one in six citations misstates its
source in some way, with no improvement over time (Baethge & Jergas, 2025,
https://doi.org/10.1186/s41073-025-00173-z); the earlier meta-analysis put the
total error rate near one in four (Jergas & Baethge, 2015,
https://doi.org/10.7717/peerj.1364). Neither reviewers nor editors routinely
check. This tool exists to make the check cheap enough to happen. The final
read of any flagged citation is yours.

## What it does and does not establish

It establishes that a claim-source pair deserves a human look, with the
relevant source passages quoted so that look takes seconds. It does **not**:

- prove a citation is wrong ("not found" means not found in the passages
  retrieved; retrieval can miss support that is elsewhere in the source);
- prove a citation is right ("consistent" reflects only the passages shown);
- judge whether the claim itself is true, only whether the source says it;
- check that references exist. That is the job of its sibling tool,
  [citation-verifier](https://github.com/WarderHouse/citation-verifier):
  run `citeverify` for existence, `claimverify` for fidelity.

## Verdicts

Each claim-source pair gets one of:

| Verdict | Meaning |
|---|---|
| `possible_conflict` | a retrieved passage appears to cut against the claim (quoted) |
| `not_found` | nothing in the retrieved passages bears on the claim |
| `partially_consistent` | related but narrower, more hedged, or shifted; the shift is named |
| `consistent` | the passages state what the claim attributes to the source |
| `not_checkable` | background, seminal, or methods citation; no assertion to check |
| `unverifiable` | no full text for this source in the bank |
| `assessment_error` | the model call failed, or the matched file yielded no text (scanned PDF); check by hand |
| `not_assessed` | `--model none` runs: passages retrieved for your own read, no judgment made |

The report is ordered by risk, so the pairs worth human time come first.

## Confidentiality

With the default local model, **nothing leaves your machine**: the only network
traffic is to your own Ollama server on localhost, and the tool ignores
`HTTP(S)_PROXY` and system proxy settings for that call, so a managed
machine's proxy cannot silently intercept it. This is the intended mode for
manuscripts under review, which you may not upload to third-party services.
The optional `anthropic:` provider sends claim sentences, reference entries,
bank filenames, and source passages to the Anthropic API; use it only for
manuscripts you are entitled to share (for example, your own drafts). No
telemetry, ever. See [CONFIDENTIALITY.md](CONFIDENTIALITY.md).

## Install

```bash
pip install claim-verifier
```

Or from source:

```bash
git clone https://github.com/WarderHouse/claim-verifier
cd claim-verifier
pip install .
```

Python 3.10+. PDF input needs the `pdftotext` binary (`brew install poppler`
or `apt install poppler-utils`). Local assessment needs
[Ollama](https://ollama.com) with a model pulled, e.g.
`ollama pull qwen2.5:14b`.

## Quickstart

```bash
# Offline smoke test on the bundled synthetic example (no PDFs, no model)
claimverify --manuscript examples/manuscript.md --bank examples/sources --model none

# See what would be checked, with no model call at all
claimverify --manuscript paper.pdf --bank ./sources --list-claims

# Full run with a local model (default: ollama:qwen2.5:14b)
claimverify --manuscript paper.pdf --bank ./sources --out report.md

# A larger local model, capped at 20 pairs
claimverify --manuscript paper.pdf --bank ./sources \
    --model ollama:qwen2.5:32b --max-pairs 20 --out report.md

# Retrieval only: no LLM; every pair is reported "not assessed" with its
# retrieved passages printed for manual checking
claimverify --manuscript paper.pdf --bank ./sources --model none
```

The bank is a folder of full texts (`.pdf`, `.txt`, `.md`) named so the first
author's surname and year are recoverable, e.g. `Garavan et al.-2019.pdf` or
`garavan_2019.txt`. Files whose names carry no recognizable author-year are
listed on stderr as skipped, and references with no bank file are listed as
unverifiable, rather than anything being silently dropped. Where a filename
cannot carry the key, pass `--map map.json` with entries like
`{"garavan-2019": "odd_filename.pdf"}`; map targets must exist inside the bank
folder.

## How it works

1. `pdftotext` extracts the manuscript text; the reference list is split off.
2. Every sentence with an APA in-text citation (parenthetical or narrative)
   becomes a claim, joined to its reference entry by first-author surname + year.
3. For each claim-source pair with full text in the bank, BM25 retrieves the
   most relevant passages from that source.
4. The model classifies the citation's function (empirical, conceptual,
   methodological, background), then compares the attribution against the
   passages and returns a verdict, a verbatim evidence quote, and a rationale.
5. The report ranks pairs by risk, with the evidence quoted so a human can
   confirm or dismiss each flag quickly.

## Known limits (alpha)

- APA 7 only; numbered citation styles are not parsed.
- The claim unit is one sentence (with one sentence of context either side);
  claims built across paragraphs are checked sentence by sentence.
- First-author-surname + year matching can collide when two cited works share
  both. Cited co-author surnames break ties against the bank's filenames
  (co-authors the citation does not name count against a candidate), and a
  pair whose match rested on first author and year alone, on a year-suffix
  fallback, or on a tie carries an explicit caution in the report (the bank
  may hold a same-author-same-year different work while the cited one is
  absent); use `--map` to disambiguate. Lettered same-year works (2020a vs
  2020b) are never cross-matched.
- Organizational authors (United Nations, World Bank) parse imperfectly; in
  narrative position ("The World Bank (2020) reported...") they can key on the
  final word or be dropped, so they usually surface as oddly keyed
  unverifiable entries rather than bad assessments.
- Surnames the ASCII pattern cannot represent (diacritics such as Nuñez or
  Bürkner) are dropped as misses rather than truncated into wrong keys.
- The source text sits inside the model prompt, so a hostile source file can
  in principle influence its own verdict; treat verdicts on untrusted sources
  as advisory, and read reports in a viewer that does not auto-load remote
  content (quoted material is markdown-escaped as a second line of defense).
- Retrieval is lexical (BM25). A paraphrase sharing no vocabulary with its
  source can rank low, which is one reason "not found" is a flag, not a verdict.
- Small local models are more conservative and less precise than frontier
  models; expect more `not_found` flags to dismiss on human review.

## License

MIT.
