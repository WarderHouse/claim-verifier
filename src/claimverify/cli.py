"""The claimverify command."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .assess import make_provider
from .bank import SourceBank
from .extract import extract_claims, parse_references, pick_reference, split_sections
from .report import Row, render
from .textio import TextExtractionError, read_text


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="claimverify",
        description=(
            "Flag citation-bearing claims in a manuscript whose cited full text may "
            "not say what the author claims. A triage aid; the final read is yours."
        ),
    )
    p.add_argument("--manuscript", type=Path, help="Manuscript file (.pdf, .txt, .md)")
    p.add_argument("--bank", type=Path, help="Folder of cited-source full texts")
    p.add_argument(
        "--map",
        type=Path,
        default=None,
        help="JSON file mapping 'surname-year' keys to bank filenames",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write the markdown report here (default: stdout)",
    )
    p.add_argument(
        "--model",
        default="ollama:qwen2.5:14b",
        help="Assessor: 'ollama:MODEL' (local, default), 'anthropic:MODEL', or 'none' (retrieval only)",
    )
    p.add_argument(
        "--max-pairs",
        type=int,
        default=None,
        help="Assess at most N claim-source pairs",
    )
    p.add_argument(
        "--list-claims",
        action="store_true",
        help="List extracted claims and exit (no model call)",
    )
    p.add_argument("--version", action="version", version=f"claimverify {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.manuscript or not args.bank and not args.list_claims:
        build_parser().print_help()
        return 2

    try:
        text = read_text(args.manuscript)
    except (TextExtractionError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    body, ref_text = split_sections(text)
    claims = extract_claims(body)
    refs: dict[str, list] = {}
    for ref in parse_references(ref_text):
        refs.setdefault(ref.key, []).append(ref)

    if args.list_claims:
        for claim in claims:
            keys = ", ".join(k.display for k in claim.cites)
            print(f"[{keys}] {claim.sentence}")
        print(
            f"\n{len(claims)} citation-bearing sentences; {len(refs)} reference entries parsed.",
            file=sys.stderr,
        )
        return 0

    try:
        bank = SourceBank(args.bank, key_map=args.map)
    except (OSError, ValueError) as e:
        print(f"error reading bank: {e}", file=sys.stderr)
        return 1
    try:
        provider = make_provider(args.model)
    except (ValueError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    from .retrieve import rank

    rows: list[Row] = []
    unbanked: list[str] = []
    assessed = 0
    for claim in claims:
        for cite in claim.cites:
            match = bank.lookup(cite)
            if match is None:
                unbanked.append(cite.display)
                continue
            if args.max_pairs is not None and assessed >= args.max_pairs:
                continue
            passages = rank(claim.context, bank.passages_for(match.path))
            ref = pick_reference(refs.get(cite.key, []), cite)
            entry_text = ref.entry if ref else "(reference entry not parsed)"
            label = f"{cite.display} [{match.path.name}]"
            print(f"assessing {label} … ", end="", file=sys.stderr, flush=True)
            try:
                assessment = provider.assess(claim, label, entry_text, passages)
            except Exception as e:  # noqa: BLE001 - fail soft per pair, keep the run
                from .assess import Assessment

                assessment = Assessment(verdict="assessment_error", rationale=str(e))
            print(assessment.verdict, file=sys.stderr)
            rows.append(
                Row(
                    claim=claim,
                    cite_key=label,
                    assessment=assessment,
                    match_caution=match.score == 0,
                )
            )
            assessed += 1

    output = render(args.manuscript.name, args.model, rows, unbanked)
    if args.out:
        args.out.write_text(output, encoding="utf-8")
        print(f"report written to {args.out}", file=sys.stderr)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
