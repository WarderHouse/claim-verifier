"""Render the markdown report, ranked so the riskiest flags come first.

Quoted material (manuscript sentences, source passages, model text) is
markdown-escaped: a hostile or merely unlucky source could otherwise smuggle
a remote image (a beacon on report open) or counterfeit structure into the
report.
"""

from __future__ import annotations

from dataclasses import dataclass

from .assess import RISK_ORDER, Assessment
from .extract import Claim

_HEADINGS = {
    "possible_conflict": "Possible conflicts (check these first)",
    "not_found": "Not found in the passages retrieved",
    "partially_consistent": "Partially consistent (check the shift)",
    "assessment_error": "Assessment errors (re-run or check by hand)",
    "not_assessed": "Not assessed (retrieval only): passages for your own read",
    "not_checkable": "No checkable assertion",
    "consistent": "Consistent with the retrieved passages",
    "unverifiable": "Unverifiable (no full text in the bank)",
}

_PREAMBLE = """\
This report flags citation-claim pairs for a human to check. It is a triage
aid, not a judgment: "not found" means not found in the passages retrieved,
and even "consistent" reflects only the passages shown. The final read of any
flagged source is yours.
"""


def _md_safe(text: str) -> str:
    """Neutralize markdown that would render as markup inside quoted content."""
    return text.replace("<", "\\<").replace("![", "!\\[")


@dataclass
class Row:
    claim: Claim
    cite_key: str
    assessment: Assessment
    match_caution: bool = False  # bank match rested on first author + year alone


def render(
    manuscript_name: str,
    model_spec: str,
    rows: list[Row],
    unbanked: list[str],
    skipped_pairs: int = 0,
) -> str:
    order = {v: i for i, v in enumerate(RISK_ORDER)}
    rows = sorted(rows, key=lambda r: order.get(r.assessment.verdict, len(order)))

    counts: dict[str, int] = {}
    for row in rows:
        counts[row.assessment.verdict] = counts.get(row.assessment.verdict, 0) + 1

    lines = [
        f"# Claim fidelity report: {manuscript_name}",
        "",
        f"Model: `{model_spec}` · Pairs assessed: {len(rows)} · claimverify (alpha)",
        "",
        _PREAMBLE,
        "## Summary",
        "",
        "| Verdict | Pairs |",
        "|---|---|",
    ]
    for verdict in RISK_ORDER:
        if counts.get(verdict):
            lines.append(f"| {_HEADINGS[verdict]} | {counts[verdict]} |")
    unique_unbanked = sorted(set(unbanked))
    if unique_unbanked:
        lines.append(f"| {_HEADINGS['unverifiable']} | {len(unique_unbanked)} |")
    lines.append("")
    if skipped_pairs:
        lines.append(
            f"{skipped_pairs} further claim-source pairs were not assessed "
            "because --max-pairs capped the run; this report under-covers the "
            "manuscript by that many pairs."
        )
        lines.append("")

    current = None
    for row in rows:
        verdict = row.assessment.verdict
        if verdict != current:
            lines += [f"## {_HEADINGS.get(verdict, verdict)}", ""]
            current = verdict
        a = row.assessment
        lines.append(f"### {row.cite_key}")
        lines.append("")
        lines.append(f"> {_md_safe(row.claim.sentence)}")
        lines.append("")
        if row.match_caution:
            lines.append(
                "Caution: the bank file was matched on first author and year "
                "alone (or by a year-suffix fallback, or against tied "
                "candidates). Confirm it is the cited work; the bank may hold "
                "a different same-author-same-year work while the cited one "
                "is absent."
            )
            lines.append("")
        if row.claim.secondary:
            lines.append(
                'Secondary citation ("as cited in"): check the primary source directly.'
            )
            lines.append("")
        if a.citation_function:
            lines.append(
                f"Citation function: {a.citation_function} · Confidence: {a.confidence or 'n/a'}"
            )
            lines.append("")
        if a.rationale:
            lines.append(_md_safe(a.rationale))
            lines.append("")
        if verdict == "not_assessed" and a.passages:
            lines.append("Retrieved passages:")
            lines.append("")
            for p in a.passages:
                lines.append(f"> {_md_safe(p.text[:900])}")
                lines.append("")
        elif a.evidence_quote:
            lines.append(f'Evidence from the source: "{_md_safe(a.evidence_quote)}"')
            lines.append("")
        elif verdict in ("not_found", "possible_conflict") and a.passages:
            lines.append("Top retrieved passage, for your own read:")
            lines.append("")
            lines.append(f"> {_md_safe(a.passages[0].text[:600])}")
            lines.append("")

    if unique_unbanked:
        lines += [f"## {_HEADINGS['unverifiable']}", ""]
        lines.append(
            "These cited works had no full text in the bank, so nothing was checked:"
        )
        lines.append("")
        for key in unique_unbanked:
            lines.append(f"- {key}")
        lines.append("")

    return "\n".join(lines)
