"""Index a folder of source full texts and match reference entries to them.

Matching is filename-based: a bank file named like "Crocco and Zarestky-2024.pdf"
or "garavan_2019.txt" yields a first-author-surname + year key, with any further
surnames in the filename kept as a disambiguator for same-author-same-year
collisions. A reference with no bank match is reported as unverifiable, never
silently dropped. An explicit JSON map ({"surname-year": "filename"}) overrides
filename inference.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .extract import YEAR, CiteKey, co_author_score
from .textio import TEXT_SUFFIXES, TextExtractionError, read_text

_YEAR_IN_NAME = re.compile(r"[-_ ](" + YEAR + r")\b")
_SURNAME_IN_NAME = re.compile(r"[A-Z][A-Za-z'\-]+")

MIN_WORDS, MAX_WORDS = 120, 320


@dataclass
class Passage:
    source_file: str
    index: int
    text: str


@dataclass
class _Candidate:
    path: Path
    co_authors: tuple[str, ...]
    et_al: bool


class SourceBank:
    def __init__(self, folder: Path, key_map: Path | None = None):
        self.folder = folder
        self.by_key: dict[str, list[_Candidate]] = {}
        self._chunks: dict[str, list[Passage]] = {}
        self.skipped: list[str] = []
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() not in TEXT_SUFFIXES | {".pdf"}:
                continue
            ym = _YEAR_IN_NAME.search(path.stem)
            names = _SURNAME_IN_NAME.findall(path.stem[: ym.start()] if ym else "")
            if not ym or not names:
                self.skipped.append(path.name)
                continue
            key = f"{names[0].lower()}-{ym.group(1)}"
            author_area = path.stem[: ym.start()].lower()
            self.by_key.setdefault(key, []).append(
                _Candidate(path, tuple(names[1:]), "et al" in author_area)
            )
        if key_map is not None:
            mapping = json.loads(key_map.read_text(encoding="utf-8"))
            for key, filename in mapping.items():
                self.by_key[key.lower()] = [_Candidate(folder / filename, (), False)]

    def lookup(self, cite: CiteKey) -> Path | None:
        """Best candidate for the cited work: exact key first, then
        year-suffix-insensitive ('smith-2020a' ~ 'smith-2020'), co-authors
        breaking first-author-year ties."""
        candidates = self.by_key.get(cite.key)
        if not candidates:
            base = re.sub(r"[a-z]$", "", cite.key)
            merged: list[_Candidate] = []
            for cand_key, cands in self.by_key.items():
                if re.sub(r"[a-z]$", "", cand_key) == base:
                    merged.extend(cands)
            candidates = merged
        if not candidates:
            return None
        best = max(
            candidates, key=lambda c: co_author_score(cite, c.co_authors, c.et_al)
        )
        return best.path

    def passages_for(self, path: Path | None) -> list[Passage]:
        if path is None:
            return []
        if path.name not in self._chunks:
            try:
                text = read_text(path)
            except TextExtractionError:
                self._chunks[path.name] = []
                return []
            self._chunks[path.name] = _chunk(text, path.name)
        return self._chunks[path.name]


def _chunk(text: str, source_file: str) -> list[Passage]:
    """Merge paragraphs into passages of roughly MIN_WORDS..MAX_WORDS words."""
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    paras = [p for p in paras if len(p.split()) > 3]
    passages: list[Passage] = []
    buf: list[str] = []
    count = 0
    for para in paras:
        words = len(para.split())
        if count and count + words > MAX_WORDS:
            passages.append(Passage(source_file, len(passages), " ".join(buf)))
            buf, count = [], 0
        buf.append(para)
        count += words
        if count >= MIN_WORDS:
            passages.append(Passage(source_file, len(passages), " ".join(buf)))
            buf, count = [], 0
    if buf:
        passages.append(Passage(source_file, len(passages), " ".join(buf)))
    return passages
