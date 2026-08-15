# Confidentiality

This tool was designed for a setting where confidentiality is not optional:
checking a manuscript under peer review, which reviewers and editors are
generally prohibited from uploading to third-party services.

## Default mode (Ollama): fully local

With the default `--model ollama:...`, the only network traffic is HTTP to
your own Ollama server at `localhost:11434`. The manuscript text, the source
full texts, the retrieved passages, and the model's assessments never leave
your machine. Retrieval (BM25) is pure Python, offline. There is no telemetry,
no update check, and no call to any external service.

## `--model none`: no model at all

Retrieval-only mode produces the claim list and the top passages for fully
manual checking. Nothing leaves the machine and no model runs.

## `--model anthropic:...`: explicitly off-machine

The Anthropic provider sends, for each claim-source pair, the claim sentence
and its immediate context, the reference entry, and the retrieved source
passages to the Anthropic API. Use this only for manuscripts you are entitled
to share, such as your own drafts before submission. Do not use it for
manuscripts you are reviewing unless the journal's policy explicitly permits
it. The API key comes from the `ANTHROPIC_API_KEY` environment variable and is
never written to disk by this tool.

## What is on disk

The markdown report quotes manuscript sentences and short source passages.
Treat the report with the same confidentiality as the manuscript itself.
