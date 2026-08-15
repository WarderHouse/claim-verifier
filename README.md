# claim-verifier

Flag citation-bearing claims in a manuscript whose cited full text may not say
what the author claims. `claimverify` reads a manuscript, finds every sentence
that carries an APA in-text citation, retrieves the most relevant passages from
a folder of cited-source full texts you supply, and asks a language model (a
local one by default) whether each passage matches what the sentence attributes
to that source. The output is a ranked markdown report a human works through.

It is a triage aid, not a judge. Quotation-error studies in medicine estimate
that roughly one in six citations misrepresents its source in some way
(Baethge & Jergas, 2025, https://doi.org/10.1186/s41073-025-00173-z; Jergas &
Baethge, 2015, https://doi.org/10.7717/peerj.1364), and neither reviewers nor
editors routinely check. This tool exists to make the check cheap enough to
happen. The final read of any flagged citation is yours.

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

The report is ordered by risk, so the pairs worth human time come first.

## Confidentiality

With the default local model, **nothing leaves your machine**: the only network
traffic is to your own Ollama server on localhost. This is the intended mode
for manuscripts under review, which you may not upload to third-party
services. The optional `anthropic:` provider sends claim sentences and source
passages to the Anthropic API; use it only for manuscripts you are entitled to
share (for example, your own drafts). No telemetry, ever. See
[CONFIDENTIALITY.md](CONFIDENTIALITY.md).

## Install

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
# See what would be checked, with no model call at all
claimverify --manuscript paper.pdf --bank ./sources --list-claims

# Full run with a local model (default: ollama:qwen2.5:14b)
claimverify --manuscript paper.pdf --bank ./sources --out report.md

# A larger local model, capped at 20 pairs
claimverify --manuscript paper.pdf --bank ./sources \
    --model ollama:qwen2.5:32b --max-pairs 20 --out report.md

# Retrieval only: no LLM, just the passages for manual checking
claimverify --manuscript paper.pdf --bank ./sources --model none
```

The bank is a folder of full texts (`.pdf`, `.txt`, `.md`) named so the first
author's surname and year are recoverable, e.g. `Garavan et al.-2019.pdf` or
`garavan_2019.txt`. References with no bank file are listed as unverifiable
rather than silently skipped. Where a filename cannot carry the key, pass
`--map map.json` with entries like `{"garavan-2019": "odd_filename.pdf"}`.

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
  both; use `--map` to disambiguate.
- Retrieval is lexical (BM25). A paraphrase sharing no vocabulary with its
  source can rank low, which is one reason "not found" is a flag, not a verdict.
- Small local models are more conservative and less precise than frontier
  models; expect more `not_found` flags to dismiss on human review.

## License

MIT.
