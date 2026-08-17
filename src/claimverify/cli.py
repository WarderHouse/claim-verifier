"""The claimverify command."""

from __future__ import annotations

import argparse
import os
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

    if args.out and not args.out.parent.exists():
        # Fail before the model run, not after it: a bad --out path discovered
        # at write time would discard the whole run's work.
        print(
            f"error: --out directory does not exist: {args.out.parent}", file=sys.stderr
        )
        return 1

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
        bank = None
        if args.bank and args.bank.is_dir():
            try:
                bank = SourceBank(args.bank, key_map=args.map)
            except (OSError, ValueError):
                bank = None
        for claim in claims:
            parts = []
            for k in claim.cites:
                marker = ""
                if bank is not None and bank.lookup(k) is None:
                    marker = " [no full text]"
                parts.append(f"{k.display}{marker}")
            print(f"[{', '.join(parts)}] {claim.sentence}")
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
    if bank.skipped:
        print(
            "bank: skipped (no recognizable Author-Year filename): "
            + ", ".join(bank.skipped),
            file=sys.stderr,
        )
    try:
        provider = make_provider(args.model)
    except (ValueError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    from .assess import Assessment
    from .retrieve import rank

    def safe_error(e: Exception) -> str:
        # Exception text becomes report content; never let a secret ride along.
        msg = f"{type(e).__name__}: {e}"
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if key:
            msg = msg.replace(key, "[redacted]")
        return msg

    rows: list[Row] = []
    unbanked: list[str] = []
    assessed = 0
    skipped_overflow = 0
    for claim in claims:
        for cite in claim.cites:
            match = bank.lookup(cite)
            if match is None:
                unbanked.append(cite.display)
                continue
            if args.max_pairs is not None and assessed >= args.max_pairs:
                skipped_overflow += 1
                continue
            passages = rank(claim.context, bank.passages_for(match.path))
            ref = pick_reference(refs.get(cite.key, []), cite)
            entry_text = ref.entry if ref else "(reference entry not parsed)"
            label = f"{cite.display} [{match.path.name}]"
            print(f"assessing {label} … ", end="", file=sys.stderr, flush=True)
            if not passages:
                assessment = Assessment(
                    verdict="assessment_error",
                    rationale="No text could be extracted from the matched "
                    "source file (scanned PDF without a text layer, or an "
                    "unreadable file); check it by hand.",
                )
            else:
                try:
                    assessment = provider.assess(claim, label, entry_text, passages)
                except Exception as e:  # noqa: BLE001 - fail soft per pair, keep the run
                    assessment = Assessment(
                        verdict="assessment_error", rationale=safe_error(e)
                    )
            print(assessment.verdict, file=sys.stderr)
            rows.append(
                Row(
                    claim=claim,
                    cite_key=label,
                    assessment=assessment,
                    match_caution=match.score <= 0,
                )
            )
            assessed += 1
    if skipped_overflow:
        print(
            f"{skipped_overflow} pairs beyond --max-pairs were not assessed.",
            file=sys.stderr,
        )

    output = render(
        args.manuscript.name, args.model, rows, unbanked, skipped_pairs=skipped_overflow
    )
    if args.out:
        args.out.write_text(output, encoding="utf-8")
        print(f"report written to {args.out}", file=sys.stderr)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
