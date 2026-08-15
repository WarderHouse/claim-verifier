"""Extract citation-bearing claims and the reference list from manuscript text.

APA 7 in-text conventions only (parenthetical and narrative citations). The
parser is deliberately conservative: a missed citation costs one unchecked
claim, while a hallucinated one costs the user's trust, so ambiguous matches
are dropped.

The join key between a claim, a reference entry, and a bank file is
first-author surname + year, with cited co-author surnames (and "et al.") as a
disambiguator: APA gives same-year works letter suffixes only when the author
lists are identical, so an author with several same-year collaborations
produces genuine first-author-year collisions that only co-authors resolve.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

YEAR = r"(?:19|20)\d{2}[a-z]?"
SURNAME = r"[A-Z][A-Za-z'\-]+"

# Sentence-split protection for common academic abbreviations.
_ABBREV = [
    "et al.",
    "e.g.",
    "i.e.",
    "cf.",
    "vs.",
    "etc.",
    "Fig.",
    "no.",
    "Vol.",
    "pp.",
    "p.",
]

_PAREN_CITE = re.compile(r"\(([^()]{0,400}?" + YEAR + r"[^()]{0,80}?)\)")
_NARRATIVE = re.compile(
    r"(" + SURNAME + r")"
    r"((?:\s+(?:and|&)\s+" + SURNAME + r")|(?:\s+et al\.?)|(?:,\s*" + SURNAME + r")*"
    r")?[\s,]*\((" + YEAR + r")"
)
_SURNAME_RE = re.compile(SURNAME)
_YEAR_RE = re.compile(YEAR)
_REF_HEAD = re.compile(r"^\s*(references|bibliography|works cited)\s*$", re.IGNORECASE)
_CUE_WORDS = re.compile(
    r"^(?:see(?: also)?|e\.g\.|i\.e\.|cf\.|as cited in|for example|but see)[,\s]*",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CiteKey:
    """First-author surname + year, plus co-author surnames for disambiguation."""

    surname: str
    year: str
    co_authors: tuple[str, ...] = ()
    et_al: bool = False

    @property
    def key(self) -> str:
        return f"{self.surname.lower()}-{self.year}"

    @property
    def display(self) -> str:
        if self.co_authors:
            return f"{self.key} (+ {', '.join(self.co_authors)})"
        if self.et_al:
            return f"{self.key} (et al.)"
        return self.key


@dataclass
class Claim:
    sentence: str
    context: str
    cites: list[CiteKey] = field(default_factory=list)
    secondary: bool = False  # "as cited in": the author never read the source


@dataclass
class Reference:
    key: str
    entry: str
    co_authors: tuple[str, ...] = ()


def co_author_score(cite: CiteKey, cand_co: tuple[str, ...], cand_et_al: bool) -> int:
    """How well a candidate (bank file or reference entry) fits a citation's authors."""
    cand_lower = {c.lower() for c in cand_co}
    score = 0
    for author in cite.co_authors:
        if author.lower() in cand_lower:
            score += 2
    if cite.et_al and (cand_et_al or len(cand_co) >= 2):
        score += 1
    if not cite.co_authors and not cite.et_al and not cand_co and not cand_et_al:
        score += 2
    return score


def _surnames(text: str) -> tuple[str, ...]:
    return tuple(_SURNAME_RE.findall(text))


def split_sections(text: str) -> tuple[str, str]:
    """Split manuscript text into (body, reference list) at the last References heading."""
    lines = text.split("\n")
    head_idx = None
    for i, line in enumerate(lines):
        if _REF_HEAD.match(line):
            head_idx = i
    if head_idx is None:
        return text, ""
    return "\n".join(lines[:head_idx]), "\n".join(lines[head_idx + 1 :])


def split_sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text).strip()
    for i, ab in enumerate(_ABBREV):
        flat = flat.replace(ab, f"\x00{i}\x00")
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(\"'])", flat)
    out = []
    for part in parts:
        for i, ab in enumerate(_ABBREV):
            part = part.replace(f"\x00{i}\x00", ab)
        part = part.strip()
        if part:
            out.append(part)
    return out


def _keys_from_paren(content: str) -> list[CiteKey]:
    keys: list[CiteKey] = []
    for segment in content.split(";"):
        # "(Deci, 1971, as cited in Ryan, 2000)" is two works, not one author
        # with two years, so split before assigning years to an author.
        for part in re.split(r",?\s+as cited in\s+", segment, flags=re.IGNORECASE):
            part = _CUE_WORDS.sub("", part.strip())
            years = _YEAR_RE.findall(part)
            if not years:
                continue
            author_part = part[: part.find(years[0])]
            names = _surnames(author_part)
            if not names:
                continue  # a bare year like "(2020)" or a stat, not a citation
            et_al = "et al" in author_part.lower()
            for year in years:
                keys.append(CiteKey(names[0], year, names[1:], et_al))
    return keys


def extract_claims(body: str) -> list[Claim]:
    sentences = split_sentences(body)
    claims: list[Claim] = []
    for i, sent in enumerate(sentences):
        keys: list[CiteKey] = []
        for m in _PAREN_CITE.finditer(sent):
            keys.extend(_keys_from_paren(m.group(1)))
        # Blank only author-bearing parentheticals before the narrative pass:
        # the bare "(2019)" of "Garavan et al. (2019)" must survive it.
        blanked = _PAREN_CITE.sub(
            lambda m: " " if _keys_from_paren(m.group(1)) else m.group(0), sent
        )
        for m in _NARRATIVE.finditer(blanked):
            tail = m.group(2) or ""
            keys.append(
                CiteKey(
                    m.group(1),
                    m.group(3),
                    _surnames(tail),
                    "et al" in tail.lower(),
                )
            )
        if not keys:
            continue
        seen: set[CiteKey] = set()
        unique = [k for k in keys if not (k in seen or seen.add(k))]
        context = " ".join(sentences[max(0, i - 1) : i + 2])
        claims.append(
            Claim(
                sentence=sent,
                context=context,
                cites=unique,
                secondary="as cited in" in sent.lower(),
            )
        )
    return claims


def parse_references(ref_text: str) -> list[Reference]:
    """Split the reference list into entries keyed by first-author surname + year."""
    lines = [ln.rstrip() for ln in ref_text.split("\n")]
    entry_start = re.compile(
        r"^(?:" + SURNAME + r",\s|[A-Z][^.\n]{0,80}?\.?\s*\(" + YEAR + r"\))"
    )
    entries: list[str] = []
    current: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        if entry_start.match(line) and current and _YEAR_RE.search(" ".join(current)):
            entries.append(" ".join(current))
            current = []
        current.append(line.strip())
    if current:
        entries.append(" ".join(current))

    refs: list[Reference] = []
    for entry in entries:
        ym = re.search(r"\((" + YEAR + r")\)", entry)
        if not ym:
            continue
        names = _surnames(entry[: ym.start()])
        if not names:
            continue
        refs.append(
            Reference(
                key=f"{names[0].lower()}-{ym.group(1)}",
                entry=entry,
                co_authors=names[1:],
            )
        )
    return refs


def pick_reference(candidates: list[Reference], cite: CiteKey) -> Reference | None:
    """Choose the reference entry that best matches the citation's co-authors."""
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda r: co_author_score(cite, r.co_authors, len(r.co_authors) >= 2),
    )
