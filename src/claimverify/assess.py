"""Assess one claim-source pair with a language model and return a graded verdict.

The verdict vocabulary is the contract of the whole tool:

- consistent            the retrieved passages say what the claim attributes to them
- partially_consistent  related, but narrower, older, more hedged, or shifted
- not_found             nothing in the retrieved passages bears on the claim
                        (retrieval can miss; this is a flag, not a judgment)
- possible_conflict     a retrieved passage appears to cut against the claim
- not_checkable         the citation is background, seminal attribution, or a
                        methods citation; there is no assertion to check

Two verdicts are assigned without a model: unverifiable (no full text in the
bank) and assessment_error (the model call or its JSON failed). The model is
never asked whether the author is right, only whether the passages match the
attribution, and it must quote its evidence so a human can check it in seconds.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

import requests

from .bank import Passage
from .extract import Claim

VERDICTS = [
    "consistent",
    "partially_consistent",
    "not_found",
    "possible_conflict",
    "not_checkable",
]

RISK_ORDER = [
    "possible_conflict",
    "not_found",
    "partially_consistent",
    "assessment_error",
    "not_assessed",
    "not_checkable",
    "consistent",
    "unverifiable",
]

SYSTEM_PROMPT = """You are a careful research assistant helping a human check whether a manuscript's citations are used faithfully. You will see one sentence from a manuscript (with surrounding context), one cited source, and passages retrieved from that source's full text.

Work in two steps.

Step 1. Classify the citation's function: empirical_finding, conceptual_or_definition, methodological, or background_attribution. If the sentence makes no checkable assertion about the source's content (a methods citation, a seminal nod, general background), the verdict is not_checkable and you stop.

Step 2. Otherwise, compare only the attribution against the passages:
- consistent: the passages state what the sentence attributes to this source.
- partially_consistent: the passages say something related but narrower, more hedged, about a different population, or otherwise shifted. Name the shift.
- not_found: the passages do not bear on the claim. Say "not found in the passages retrieved"; the full text may still contain support elsewhere.
- possible_conflict: a passage appears to say something that cuts against the claim. Quote it.

Rules: judge only this one cited source, even if the sentence cites several. Never judge whether the claim is true, only whether the source says it. evidence_quote must be copied verbatim from a passage (or empty for not_found/not_checkable). Be conservative: when torn between two verdicts, choose the one that sends a human to look.

Respond with only a JSON object:
{"citation_function": "...", "verdict": "...", "evidence_quote": "...", "rationale": "one or two sentences", "confidence": "high|medium|low"}"""


@dataclass
class Assessment:
    verdict: str
    citation_function: str = ""
    evidence_quote: str = ""
    rationale: str = ""
    confidence: str = ""
    passages: list[Passage] = field(default_factory=list)
    raw: str = ""


def build_user_prompt(
    claim: Claim, cite_key: str, ref_entry: str, passages: list[Passage]
) -> str:
    blocks = "\n\n".join(f"[Passage {i + 1}]\n{p.text}" for i, p in enumerate(passages))
    return (
        f"MANUSCRIPT SENTENCE (the claim to check):\n{claim.sentence}\n\n"
        f"SURROUNDING CONTEXT:\n{claim.context}\n\n"
        f"CITED SOURCE UNDER CHECK: {cite_key}\n"
        f"REFERENCE ENTRY: {ref_entry}\n\n"
        f"PASSAGES RETRIEVED FROM THAT SOURCE:\n{blocks}"
    )


def _parse(raw: str, passages: list[Passage]) -> Assessment:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return Assessment(verdict="assessment_error", raw=raw)
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return Assessment(verdict="assessment_error", raw=raw)
    verdict = str(data.get("verdict", "")).strip()
    if verdict not in VERDICTS:
        return Assessment(verdict="assessment_error", raw=raw)

    # Model-returned strings can carry newlines that would forge report
    # structure (a rationale containing "\n## ..." renders as a heading).
    def flat(value: object) -> str:
        return re.sub(r"\s+", " ", str(value)).strip()

    return Assessment(
        verdict=verdict,
        citation_function=flat(data.get("citation_function", "")),
        evidence_quote=flat(data.get("evidence_quote", "")),
        rationale=flat(data.get("rationale", "")),
        confidence=flat(data.get("confidence", "")),
        passages=passages,
        raw=raw,
    )


class OllamaProvider:
    """Local assessment via the Ollama HTTP API. Nothing leaves the machine.

    Request modes, tried in order until one parses: strict JSON format (fast
    path for models with reliable structured output, e.g. the qwen2.5 family);
    no format constraint with thinking disabled (reasoning models can return an
    empty or non-JSON body under a strict format constraint); bare request
    (hosts or models that reject the think field). The first mode that succeeds
    is cached for the rest of the run.
    """

    name = "ollama"

    def __init__(self, model: str, host: str = "http://localhost:11434"):
        self.model = model
        self.host = host
        self._mode: int | None = None
        # trust_env=False ignores HTTP(S)_PROXY and system proxy settings:
        # on proxied (often university-managed) machines, requests would
        # otherwise route even localhost calls through the proxy, silently
        # breaking the nothing-leaves-your-machine promise.
        self._session = requests.Session()
        self._session.trust_env = False

    def assess(
        self, claim: Claim, cite_key: str, ref_entry: str, passages: list[Passage]
    ) -> Assessment:
        modes: list[dict] = [{"format": "json"}, {"think": False}, {}]
        order = [self._mode] if self._mode is not None else []
        order += [i for i in range(len(modes)) if i not in order]
        last = Assessment(verdict="assessment_error")
        for i in order:
            try:
                raw = self._call(modes[i], claim, cite_key, ref_entry, passages)
            except requests.RequestException as e:
                last = Assessment(verdict="assessment_error", rationale=str(e))
                continue
            last = _parse(raw, passages)
            if last.verdict != "assessment_error":
                self._mode = i
                return last
        return last

    def _call(self, extra, claim, cite_key, ref_entry, passages) -> str:
        resp = self._session.post(
            f"{self.host}/api/generate",
            json={
                "model": self.model,
                "system": SYSTEM_PROMPT,
                "prompt": build_user_prompt(claim, cite_key, ref_entry, passages),
                "stream": False,
                "options": {"temperature": 0, "num_ctx": 8192},
                **extra,
            },
            timeout=600,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")


class AnthropicProvider:
    """Assessment via the Anthropic API. Sends claim + passages off-machine;
    only for manuscripts you are entitled to share (for example, your own)."""

    name = "anthropic"

    def __init__(self, model: str):
        self.model = model or "claude-sonnet-5"
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        if not re.fullmatch(r"[\x21-\x7e]+", self.api_key):
            # Never echo the value: a malformed key inside an exception message
            # could end up in a report a user shares.
            raise RuntimeError(
                "ANTHROPIC_API_KEY contains whitespace or non-printable "
                "characters; re-export it cleanly."
            )

    def assess(
        self, claim: Claim, cite_key: str, ref_entry: str, passages: list[Passage]
    ) -> Assessment:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 1024,
                "system": SYSTEM_PROMPT,
                "messages": [
                    {
                        "role": "user",
                        "content": build_user_prompt(
                            claim, cite_key, ref_entry, passages
                        ),
                    }
                ],
            },
            timeout=120,
        )
        resp.raise_for_status()
        parts = resp.json().get("content", [])
        text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
        return _parse(text, passages)


class NullProvider:
    """No model: emit the retrieved passages for fully manual checking."""

    name = "none"

    def assess(
        self, claim: Claim, cite_key: str, ref_entry: str, passages: list[Passage]
    ) -> Assessment:
        return Assessment(
            verdict="not_assessed",
            rationale="No model configured; the retrieved passages follow for "
            "your own read.",
            passages=passages,
        )


def make_provider(spec: str):
    """Parse 'ollama:qwen2.5:14b', 'anthropic:claude-sonnet-5', or 'none'."""
    provider, _, model = spec.partition(":")
    if provider == "ollama":
        return OllamaProvider(model or "qwen2.5:14b")
    if provider == "anthropic":
        return AnthropicProvider(model)
    if provider in ("none", "null"):
        return NullProvider()
    raise ValueError(
        f"Unknown provider in --model '{spec}' (use ollama:…, anthropic:…, or none)"
    )
