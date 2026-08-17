"""Index a folder of source full texts and match reference entries to them.

Matching is filename-based: a bank file named like "Crocco and Zarestky-2024.pdf"
or "garavan_2019.txt" yields a first-author-surname + year key, with any further
surnames in the filename kept as a disambiguator for same-author-same-year
collisions. A reference with no bank match is reported as unverifiable, never
silently dropped. An explicit JSON map ({"surname-year": "filename"}) overrides
filename inference; map targets must live inside the bank folder.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .extract import _NON_SURNAME_TOKENS, YEAR, CiteKey, co_author_score
from .textio import TEXT_SUFFIXES, TextExtractionError, read_text

_YEAR_IN_NAME = re.compile(r"[-_ (](" + YEAR + r")\b")
_NAME_TOKEN = re.compile(r"[A-Za-z][A-Za-z'\-]+")
_SUFFIX = re.compile(r"[a-z]$")

MIN_WORDS, MAX_WORDS = 120, 320
_BANK_SUFFIXES = TEXT_SUFFIXES | {".pdf"}


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


@dataclass
class Match:
    path: Path
    score: int
    # score <= 0 means the join rests on first author + year alone (or on a
    # year-suffix fallback, or on an unresolvable tie); the caller must surface
    # that as a caution, because the bank may hold a same-author-same-year
    # different work while the cited one is absent.


def _filename_names(stem_author_area: str) -> tuple[str, ...]:
    """Surname tokens from a filename's author area, tolerating lowercase
    naming ("garavan_2019") and dropping connector words ("et", "al", "and")."""
    skip = _NON_SURNAME_TOKENS | {"et", "al", "and"}
    return tuple(
        t for t in _NAME_TOKEN.findall(stem_author_area) if t.lower() not in skip
    )


class SourceBank:
    def __init__(self, folder: Path, key_map: Path | None = None):
        self.folder = folder
        self.by_key: dict[str, list[_Candidate]] = {}
        self._chunks: dict[str, list[Passage]] = {}
        self.skipped: list[str] = []
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() not in _BANK_SUFFIXES:
                continue
            ym = _YEAR_IN_NAME.search(path.stem)
            names = _filename_names(path.stem[: ym.start()] if ym else "")
            if not ym or not names:
                self.skipped.append(path.name)
                continue
            key = f"{names[0].lower()}-{ym.group(1)}"
            author_area = path.stem[: ym.start()].lower()
            self.by_key.setdefault(key, []).append(
                _Candidate(path, names[1:], "et al" in author_area)
            )
        if key_map is not None:
            mapping = json.loads(key_map.read_text(encoding="utf-8"))
            if not isinstance(mapping, dict):
                raise ValueError("--map must be a JSON object of key: filename pairs")
            root = folder.resolve()
            for key, filename in mapping.items():
                if not isinstance(filename, str):
                    raise ValueError(
                        f"--map value for '{key}' is not a filename string"
                    )
                target = (folder / filename).resolve()
                if not target.is_relative_to(root):
                    raise ValueError(
                        f"--map target '{filename}' is outside the bank folder"
                    )
                if target.suffix.lower() not in _BANK_SUFFIXES:
                    raise ValueError(
                        f"--map target '{filename}' is not a .pdf/.txt/.md"
                    )
                if not target.is_file():
                    raise ValueError(f"--map target '{filename}' does not exist")
                self.by_key[key.lower()] = [_Candidate(target, (), False)]

    def lookup(self, cite: CiteKey) -> Match | None:
        """Best candidate for the cited work. Exact key first; a tie between
        distinct files, or any year-suffix fallback, returns score 0 so the
        report's caution fires. Two different letter suffixes (2020a vs 2020b)
        never match each other: by APA convention those works share an author
        list, so nothing could disambiguate them."""
        candidates = self.by_key.get(cite.key)
        fallback = False
        if not candidates:
            fallback = True
            cite_suffix = _SUFFIX.search(cite.key)
            base = _SUFFIX.sub("", cite.key)
            merged: list[_Candidate] = []
            for cand_key, cands in self.by_key.items():
                if _SUFFIX.sub("", cand_key) != base or cand_key == cite.key:
                    continue
                cand_suffix = _SUFFIX.search(cand_key)
                if cite_suffix and cand_suffix:
                    continue  # 2020a vs 2020b: different works by definition
                merged.extend(cands)
            candidates = merged
        if not candidates:
            return None
        scored = sorted(
            candidates,
            key=lambda c: co_author_score(cite, c.co_authors, c.et_al),
            reverse=True,
        )
        best = scored[0]
        best_score = co_author_score(cite, best.co_authors, best.et_al)
        tied = [
            c
            for c in scored
            if co_author_score(cite, c.co_authors, c.et_al) == best_score
            and c.path != best.path
        ]
        if fallback or tied:
            return Match(best.path, 0)
        return Match(best.path, best_score)

    def passages_for(self, path: Path | None) -> list[Passage]:
        if path is None:
            return []
        cache_key = str(path.resolve())
        if cache_key not in self._chunks:
            try:
                text = read_text(path)
            except (TextExtractionError, OSError):
                self._chunks[cache_key] = []
                return []
            self._chunks[cache_key] = _chunk(text, path.name)
        return self._chunks[cache_key]


def _chunk(text: str, source_file: str) -> list[Passage]:
    """Merge paragraphs into passages of roughly MIN_WORDS..MAX_WORDS words.
    A single paragraph longer than MAX_WORDS (pdftotext output of two-column
    PDFs often has no blank lines at all) is split on fixed word windows, so
    retrieval always has multiple passages to rank."""
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    paras = [p for p in paras if len(p.split()) > 3]
    windows: list[str] = []
    for para in paras:
        words = para.split()
        if len(words) <= MAX_WORDS:
            windows.append(para)
        else:
            for i in range(0, len(words), MAX_WORDS):
                windows.append(" ".join(words[i : i + MAX_WORDS]))
    passages: list[Passage] = []
    buf: list[str] = []
    count = 0
    for para in windows:
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
