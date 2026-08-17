"""Rank a source's passages against a claim with BM25 (pure Python, offline).

Retrieval can miss: a claim genuinely supported by a passage that does not
share its vocabulary will rank low. Downstream wording must therefore say
"not found in the passages retrieved," never "not in the source."
"""

from __future__ import annotations

import math
import re
from collections import Counter

from .bank import Passage
from .extract import strip_citation_noise

_TOKEN = re.compile(r"[a-z0-9]+")
K1, B = 1.5, 0.75

_STOP = frozenset(
    "the a an and or of to in for on with as by at from that this is are was were be been "
    "has have had it its not no than then so such which who whom these those we our their "
    "his her they them he she you your i but if into about between among also more most "
    "can could may might will would should".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


def rank(query: str, passages: list[Passage], top_k: int = 4) -> list[Passage]:
    if not passages:
        return []
    docs = [tokenize(p.text) for p in passages]
    doc_freq: Counter[str] = Counter()
    for doc in docs:
        doc_freq.update(set(doc))
    n = len(docs)
    avg_len = sum(len(d) for d in docs) / n if n else 0.0

    def score(q_tokens: list[str], doc: list[str]) -> float:
        tf = Counter(doc)
        s = 0.0
        for term in q_tokens:
            if term not in tf:
                continue
            idf = math.log(1 + (n - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            denom = tf[term] + K1 * (1 - B + B * len(doc) / avg_len) if avg_len else 1.0
            s += idf * tf[term] * (K1 + 1) / denom
        return s

    # Citation markers and bare years in the query make the source's own
    # reference list outrank its body text; strip them before tokenizing.
    q = tokenize(strip_citation_noise(query))
    scored = sorted(
        zip(passages, docs, strict=True), key=lambda pd: score(q, pd[1]), reverse=True
    )
    return [p for p, _ in scored[:top_k]]
