import json

from claimverify.assess import _parse, make_provider
from claimverify.bank import Passage
from claimverify.cli import main
from claimverify.extract import CiteKey, Claim
from claimverify.report import Row, render


def test_parse_valid_json():
    raw = json.dumps(
        {
            "citation_function": "empirical_finding",
            "verdict": "partially_consistent",
            "evidence_quote": "participation lagged by nine points",
            "rationale": "The source reports nine points, the claim says ten.",
            "confidence": "medium",
        }
    )
    a = _parse(raw, [])
    assert a.verdict == "partially_consistent"
    assert "nine points" in a.evidence_quote


def test_parse_rejects_unknown_verdict_and_bad_json():
    assert _parse('{"verdict": "definitely_wrong"}', []).verdict == "assessment_error"
    assert _parse("no json here", []).verdict == "assessment_error"


def test_make_provider_specs():
    assert make_provider("none").name == "none"
    assert make_provider("ollama:qwen2.5:14b").model == "qwen2.5:14b"
    try:
        make_provider("mystery:model")
        raise AssertionError("should have raised")
    except ValueError:
        pass


def _row(verdict: str, key: str = "crocco-2018") -> Row:
    claim = Claim(
        sentence="A claim (Crocco, 2018).",
        context="ctx",
        cites=[CiteKey("Crocco", "2018")],
    )
    a = _parse(
        json.dumps({"verdict": verdict, "citation_function": "empirical_finding"}),
        [Passage("f", 0, "text")],
    )
    return Row(claim=claim, cite_key=key, assessment=a)


def test_report_orders_by_risk_and_counts():
    rows = [_row("consistent"), _row("possible_conflict"), _row("not_found")]
    out = render("m.pdf", "none", rows, unbanked=["garavan-2019"])
    assert (
        out.index("Possible conflicts")
        < out.index("Not found")
        < out.index("Consistent")
    )
    assert "garavan-2019" in out
    assert "triage" in out


def test_cli_end_to_end_offline(tmp_path, capsys):
    (tmp_path / "manuscript.txt").write_text(
        "Training access varies by gender (Zarestky, 2024). No citation here.\n\n"
        "References\n\nZarestky, J. (2024). Training access. HRDQ, 35(1), 1-20.\n",
        encoding="utf-8",
    )
    bankdir = tmp_path / "bank"
    bankdir.mkdir()
    (bankdir / "Zarestky-2024.txt").write_text(
        "We find gendered differences in access to employer training.", encoding="utf-8"
    )
    rc = main(
        [
            "--manuscript",
            str(tmp_path / "manuscript.txt"),
            "--bank",
            str(bankdir),
            "--model",
            "none",
            "--out",
            str(tmp_path / "report.md"),
        ]
    )
    assert rc == 0
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "zarestky-2024" in report
    assert "passages retrieved" in report


def test_cli_list_claims(tmp_path, capsys):
    (tmp_path / "m.txt").write_text("A finding (Crocco, 2018).", encoding="utf-8")
    rc = main(
        [
            "--manuscript",
            str(tmp_path / "m.txt"),
            "--bank",
            str(tmp_path),
            "--list-claims",
        ]
    )
    assert rc == 0
    assert "crocco-2018" in capsys.readouterr().out
