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

The local call deliberately ignores `HTTP_PROXY`/`HTTPS_PROXY` environment
variables and system proxy settings (`trust_env` is disabled): on
proxy-configured machines, HTTP libraries otherwise route even localhost
traffic through the proxy, which would silently break this promise on exactly
the managed university machines where it matters most.

## `--model none`: no model at all

Retrieval-only mode produces the claim list and the top passages for fully
manual checking. Nothing leaves the machine and no model runs.

## `--model anthropic:...`: explicitly off-machine

The Anthropic provider sends, for each claim-source pair, the claim sentence
and its immediate context, the reference entry, the bank filename of the
matched source (filenames you chose, which can themselves be revealing), the
fixed system prompt, and the retrieved source passages to the Anthropic API. Use this only for manuscripts you are entitled
to share, such as your own drafts before submission. Do not use it for
manuscripts you are reviewing unless the journal's policy explicitly permits
it. The API key comes from the `ANTHROPIC_API_KEY` environment variable and is
never written to disk by this tool.

## What is on disk

The markdown report quotes manuscript sentences and short source passages.
Treat the report with the same confidentiality as the manuscript itself.
