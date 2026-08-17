"""Extract citation-bearing claims and the reference list from manuscript text.

APA 7 in-text conventions only (parenthetical and narrative citations). The
parser is deliberately conservative: a missed citation costs one unchecked
claim, while a hallucinated one costs the user's trust, so ambiguous matches
are dropped. Names the ASCII surname pattern cannot represent (diacritics,
multi-word org authors in narrative position) are dropped as misses rather
than truncated into wrong keys.

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
# The trailing lookahead rejects a match that stops mid-word at a non-ASCII
# letter ("Nuñez" must be a miss, never the wrong key "nu").
SURNAME = r"[A-Z][A-Za-z'\-]+(?![^\W\d_])"

# Lowercase name particles kept out of surname lists ("Van der Berg" keys on
# "berg" in both narrative and parenthetical positions), plus editor markers.
_NON_SURNAME_TOKENS = {
    "van",
    "von",
    "de",
    "der",
    "den",
    "la",
    "le",
    "del",
    "di",
    "da",
    "ed",
    "eds",
}
# Sentence-initial words that precede a bare-year parenthetical without being
# authors ("The (2020) report ...").
_NARRATIVE_STOP = {
    "the",
    "this",
    "these",
    "those",
    "a",
    "an",
    "in",
    "as",
    "see",
    "but",
    "if",
    "when",
    "while",
    "although",
    "because",
    "and",
    "or",
    "of",
    "for",
}
_AUTHOR_CONNECTORS = {"and", "et", "al", "al."} | _NON_SURNAME_TOKENS

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
    r"((?:,\s*" + SURNAME + r")*(?:,?\s+(?:and|&)\s+" + SURNAME + r")?"
    r"|\s+et al\.?(?:'s)?)?"
    r"[\s,]*\((" + YEAR + r")"
)
_SURNAME_RE = re.compile(SURNAME)
# A year that is not part of a numeric range or page span ("2011-2014" and
# "pp. 2011" must not become citation years).
_YEAR_STANDALONE = re.compile(r"(?<![0-9-])((?:19|20)\d{2}[a-z]?)(?![0-9a-z-])")
_PAGE_LOCATOR = re.compile(
    r",?\s*(?:pp?|para|chap|chapter)\.?\s+[\d,\s\-]+", re.IGNORECASE
)
_YEAR_RE = re.compile(YEAR)
_REF_HEAD = re.compile(
    r"^[\s#*_]*(references|bibliography|works cited)[\s*_]*$", re.IGNORECASE
)
_CUE_WORDS = re.compile(
    r"^(?:see(?: also)?|e\.g\.|i\.e\.|cf\.|as cited in|for example|but see)[,\s]*",
    re.IGNORECASE,
)
# Author fragments may contain only name characters and connector punctuation;
# "(SD = 2019)" and "(GDP rose during 2010-2020; ...)" are not citations.
_AUTHOR_CHARS = re.compile(r"[A-Za-z'&.,\s\-]*\Z")


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
    """How well a candidate (bank file or reference entry) fits a citation's
    authors. Candidate co-authors the citation does not name count against the
    match (unless the citation is "et al.", which implies unnamed co-authors),
    so "Crocco and Grenier" prefers the two-author file over a three-author
    one that also contains Grenier."""
    cited = {c.lower() for c in cite.co_authors}
    cand_lower = [c.lower() for c in cand_co]
    score = sum(2 for c in cand_lower if c in cited)
    if cite.et_al and (cand_et_al or len(cand_co) >= 2):
        score += 1
    if not cite.co_authors and not cite.et_al and not cand_co and not cand_et_al:
        score += 2
    if not cite.et_al:
        score -= sum(1 for c in cand_lower if c not in cited)
    return score


def _clean_surname(token: str) -> str:
    """Strip possessives and stray trailing punctuation ("Bandura's" -> "Bandura",
    "COVID-" -> "COVID")."""
    token = re.sub(r"'[sS]?$", "", token)
    return token.rstrip("-'")


def _surnames(text: str) -> tuple[str, ...]:
    out = []
    for token in _SURNAME_RE.findall(text):
        token = _clean_surname(token)
        if token and token.lower() not in _NON_SURNAME_TOKENS:
            out.append(token)
    return tuple(out)


def strip_citation_noise(text: str) -> str:
    """Remove parenthetical citations and standalone year tokens, for use as a
    retrieval query: otherwise the source's own reference list, dense in years,
    outranks its body text."""
    text = _PAREN_CITE.sub(" ", text)
    return _YEAR_STANDALONE.sub(" ", text)


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
        # Boundary-aware: the "p." of "p. 12" is protected, the end of
        # "relationship." is not.
        flat = re.sub(r"(?<![A-Za-z])" + re.escape(ab), f"\x00{i}\x00", flat)
    parts = re.split(r"(?:(?<=[.!?])|(?<=[.!?][\"'”’]))\s+(?=[A-Z(\"'“‘])", flat)
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
            part = _PAGE_LOCATOR.sub("", part)
            years = _YEAR_STANDALONE.findall(part)
            if not years:
                continue
            author_part = part[: part.find(years[0])]
            if not _AUTHOR_CHARS.fullmatch(author_part):
                continue  # "(SD = 2019)": junk characters, not an author list
            lower_words = re.findall(r"(?<![A-Za-z])[a-z][a-z'.]*", author_part)
            if any(w not in _AUTHOR_CONNECTORS for w in lower_words):
                continue  # "(GDP rose during 2010...)": prose, not authors
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
            surname = _clean_surname(m.group(1))
            if not surname or surname.lower() in _NARRATIVE_STOP:
                continue
            tail = m.group(2) or ""
            keys.append(
                CiteKey(
                    surname,
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


# An entry begins with "Surname, X." (APA person, particles allowed) or an
# org-author line that reaches its (year). Requiring the initial after the
# surname keeps wrapped location lines ("Bangkok, Thailand: ...") from
# starting bogus entries.
_ENTRY_START = re.compile(
    r"^(?:(?:(?:[Vv]an|[Vv]on|[Dd]e|[Dd]er|[Dd]en|[Ll]a|[Ll]e|[Dd]el|[Dd]i|[Dd]a)\s+)*"
    + SURNAME
    + r",\s+[A-Z]\.|[A-Z][^.\n]{0,80}?\.?\s*\("
    + YEAR
    + r"\))"
)


def parse_references(ref_text: str) -> list[Reference]:
    """Split the reference list into entries keyed by first-author surname + year."""
    lines = [ln.rstrip() for ln in ref_text.split("\n")]
    entries: list[str] = []
    current: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        starts_entry = _ENTRY_START.match(line) is not None
        # Split when the accumulated entry is complete (has its year), or when
        # the new line is unmistakably a fresh entry with its own year, so a
        # no-year entry ("in press") cannot swallow its successor.
        if (
            starts_entry
            and current
            and (_YEAR_RE.search(" ".join(current)) or _YEAR_RE.search(line))
        ):
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
