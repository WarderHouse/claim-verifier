"""Regression tests for the pre-publication adversarial review findings."""

import json

import pytest

from claimverify.bank import SourceBank, _chunk
from claimverify.extract import (
    CiteKey,
    extract_claims,
    parse_references,
    split_sentences,
    strip_citation_noise,
)
from claimverify.report import Row, render
from claimverify.retrieve import rank


def keys_of(text):
    return [k.key for c in extract_claims(text) for k in c.cites]


# --- extract: hallucinated-citation classes ---------------------------------


def test_page_ranges_do_not_become_years():
    assert keys_of("Turnover fell sharply (Kim, 2019, pp. 2011-2014).") == ["kim-2019"]


def test_year_ranges_and_stats_are_not_citations():
    assert keys_of("Training grew (GDP rose during 2010-2020; Smith, 2022).") == [
        "smith-2022"
    ]
    assert keys_of("The effect held (SD = 2019) in both waves.") == []


def test_possessive_narrative_citations():
    assert keys_of("Bandura's (1977) theory guided the design.") == ["bandura-1977"]


def test_three_author_narrative_keys_on_first_author():
    claims = extract_claims("Smith, Jones and Lee (2020) found an effect.")
    cite = claims[0].cites[0]
    assert (cite.surname, cite.co_authors) == ("Smith", ("Jones", "Lee"))
    claims = extract_claims("Smith, Jones, and Lee (2020) found an effect.")
    assert claims[0].cites[0].surname == "Smith"


def test_narrative_stopword_not_a_citation():
    assert keys_of("The (2020) World Development Report shaped policy.") == []


def test_particles_key_on_capitalized_surname_both_forms():
    assert keys_of("One view (Van der Berg, 2020).") == ["berg-2020"]
    assert keys_of("Van der Berg (2020) argued otherwise.") == ["berg-2020"]


def test_diacritic_surnames_miss_rather_than_truncate():
    assert keys_of("A finding (Nuñez, 2019) held.") == []


def test_sentence_split_relationship_and_quotes():
    sents = split_sentences(
        "Trust mediates the relationship. Smith (2020) found the opposite."
    )
    assert len(sents) == 2
    sents = split_sentences('It was "the end of training." Smith (2020) disagreed.')
    assert len(sents) == 2


def test_strip_citation_noise_removes_years_and_parens():
    cleaned = strip_citation_noise("Training grew (Crocco, 2018) after 2015 reforms.")
    assert "2018" not in cleaned and "2015" not in cleaned and "Crocco" not in cleaned


# --- reference-list splitting ------------------------------------------------


def test_in_press_entry_does_not_swallow_successor():
    refs = parse_references(
        "Smith, J. (in press). The future of HRD. HRDI.\n"
        "Taylor, B. (2021). Learning climates. HRDQ, 32(1), 1-20.\n"
    )
    assert [r.key for r in refs] == ["taylor-2021"]


def test_wrapped_location_line_does_not_start_entry():
    refs = parse_references(
        "Crocco, O. S. (2018). Human resource development in\n"
        "Bangkok, Thailand: A study. HRDI, 21(2), 1-20.\n"
        "Garavan, T. (2019). Training. EJTD, 43(1), 1-10.\n"
    )
    keys = [r.key for r in refs]
    assert keys == ["crocco-2018", "garavan-2019"]


# --- bank joins --------------------------------------------------------------


def test_lettered_suffixes_never_cross_match(tmp_path):
    (tmp_path / "Smith-2020b.txt").write_text("text b", encoding="utf-8")
    bank = SourceBank(tmp_path)
    assert bank.lookup(CiteKey("Smith", "2020a")) is None


def test_suffix_fallback_always_carries_caution(tmp_path):
    (tmp_path / "Smith-2020.txt").write_text("text", encoding="utf-8")
    bank = SourceBank(tmp_path)
    match = bank.lookup(CiteKey("Smith", "2020a"))
    assert match is not None and match.score == 0


def test_unsuffixed_cite_with_multiple_suffixed_files_is_cautioned(tmp_path):
    (tmp_path / "Smith-2020a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "Smith-2020b.txt").write_text("b", encoding="utf-8")
    bank = SourceBank(tmp_path)
    assert bank.lookup(CiteKey("Smith", "2020")).score == 0


def test_uncited_coauthors_count_against_a_candidate(tmp_path):
    (tmp_path / "Crocco and Grenier-2021.txt").write_text("two", encoding="utf-8")
    (tmp_path / "Crocco Grenier and Smith-2021.txt").write_text(
        "three", encoding="utf-8"
    )
    bank = SourceBank(tmp_path)
    match = bank.lookup(CiteKey("Crocco", "2021", ("Grenier",)))
    assert match.path.name == "Crocco and Grenier-2021.txt"
    assert match.score > 0


def test_score_ties_between_distinct_files_are_cautioned(tmp_path):
    (tmp_path / "Kim and Park-2020.txt").write_text("x", encoding="utf-8")
    (tmp_path / "Kim and Lee-2020.txt").write_text("y", encoding="utf-8")
    bank = SourceBank(tmp_path)
    assert bank.lookup(CiteKey("Kim", "2020", ("Cho",))).score == 0


def test_lowercase_filenames_are_indexed(tmp_path):
    (tmp_path / "garavan_2019.txt").write_text("text", encoding="utf-8")
    bank = SourceBank(tmp_path)
    assert bank.lookup(CiteKey("Garavan", "2019")) is not None
    assert bank.skipped == []


def test_map_rejects_traversal_missing_and_nondict(tmp_path):
    (tmp_path / "Smith-2020.txt").write_text("x", encoding="utf-8")
    escape = tmp_path / "map1.json"
    escape.write_text(json.dumps({"smith-2020": "../outside.txt"}), encoding="utf-8")
    with pytest.raises(ValueError):
        SourceBank(tmp_path, key_map=escape)
    missing = tmp_path / "map2.json"
    missing.write_text(json.dumps({"smith-2020": "typo.txt"}), encoding="utf-8")
    with pytest.raises(ValueError):
        SourceBank(tmp_path, key_map=missing)
    nondict = tmp_path / "map3.json"
    nondict.write_text(json.dumps(["smith-2020"]), encoding="utf-8")
    with pytest.raises(ValueError):
        SourceBank(tmp_path, key_map=nondict)


def test_chunk_splits_wall_of_text():
    chunks = _chunk("word " * 8000, "x.txt")
    assert len(chunks) > 1
    assert all(len(c.text.split()) <= 400 for c in chunks)


def test_rank_prefers_body_over_reference_list_shape(tmp_path):
    (tmp_path / "Smith-2020.txt").write_text(
        "We found women's training participation lagged in manufacturing firms.\n\n"
        + "References Crocco, O. (2018). HRDI, 21, 1-20. Garavan, T. (2019). "
        "EJTD, 43, 2019. Smith, J. (2020). HRDQ, 31, 2020. " * 10,
        encoding="utf-8",
    )
    bank = SourceBank(tmp_path)
    passages = bank.passages_for(bank.lookup(CiteKey("Smith", "2020")).path)
    top = rank("Participation lagged for women (Smith, 2020).", passages, top_k=1)
    assert "manufacturing" in top[0].text


# --- report ------------------------------------------------------------------


def _assessment(**kw):
    from claimverify.assess import Assessment

    return Assessment(**kw)


def test_report_escapes_markdown_in_quoted_content():
    from claimverify.bank import Passage
    from claimverify.extract import Claim

    row = Row(
        claim=Claim(sentence="A claim ![beacon](https://evil/x) here.", context="c"),
        cite_key="k",
        assessment=_assessment(
            verdict="possible_conflict",
            rationale="line",
            evidence_quote="<img src=x> quote",
            passages=[Passage("f", 0, "text")],
        ),
    )
    out = render("m", "none", [row], [])
    # Backslash-escaped forms render as literal text, not markup.
    assert "!\\[beacon]" in out and "![beacon]" not in out
    assert "\\<img" in out


def test_report_counts_unbanked_unique_and_notes_cap():
    out = render("m", "none", [], ["a-2020", "a-2020", "b-2021"], skipped_pairs=3)
    assert "| Unverifiable (no full text in the bank) | 2 |" in out
    assert "--max-pairs capped the run" in out


def test_not_assessed_mode_prints_all_passages():
    from claimverify.bank import Passage
    from claimverify.extract import Claim

    row = Row(
        claim=Claim(sentence="s", context="c"),
        cite_key="k",
        assessment=_assessment(
            verdict="not_assessed",
            passages=[
                Passage("f", 0, "first passage"),
                Passage("f", 1, "second passage"),
            ],
        ),
    )
    out = render("m", "none", [row], [])
    assert "first passage" in out and "second passage" in out
    assert "Not assessed (retrieval only)" in out


# --- providers ---------------------------------------------------------------


def test_ollama_session_ignores_proxy_env():
    from claimverify.assess import OllamaProvider

    assert OllamaProvider("m")._session.trust_env is False


def test_anthropic_rejects_malformed_key_without_echo(monkeypatch):
    from claimverify.assess import AnthropicProvider

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-bad\nkey")
    with pytest.raises(RuntimeError) as exc:
        AnthropicProvider("")
    assert "sk-bad" not in str(exc.value)
