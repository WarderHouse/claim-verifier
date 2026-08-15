"""Render the markdown report, ranked so the riskiest flags come first."""

from __future__ import annotations

from dataclasses import dataclass

from .assess import RISK_ORDER, Assessment
from .extract import Claim

_HEADINGS = {
    "possible_conflict": "Possible conflicts (check these first)",
    "not_found": "Not found in the passages retrieved",
    "partially_consistent": "Partially consistent (check the shift)",
    "assessment_error": "Assessment errors (re-run or check by hand)",
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


@dataclass
class Row:
    claim: Claim
    cite_key: str
    assessment: Assessment


def render(
    manuscript_name: str, model_spec: str, rows: list[Row], unbanked: list[str]
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
    if unbanked:
        lines.append(f"| {_HEADINGS['unverifiable']} | {len(unbanked)} |")
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
        lines.append(f"> {row.claim.sentence}")
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
            lines.append(a.rationale)
            lines.append("")
        if a.evidence_quote:
            lines.append(f'Evidence from the source: "{a.evidence_quote}"')
            lines.append("")
        elif a.verdict in ("not_found", "possible_conflict") and a.passages:
            lines.append("Top retrieved passage, for your own read:")
            lines.append("")
            lines.append(f"> {a.passages[0].text[:600]}")
            lines.append("")

    if unbanked:
        lines += [f"## {_HEADINGS['unverifiable']}", ""]
        lines.append(
            "These cited works had no full text in the bank, so nothing was checked:"
        )
        lines.append("")
        for key in sorted(set(unbanked)):
            lines.append(f"- {key}")
        lines.append("")

    return "\n".join(lines)
