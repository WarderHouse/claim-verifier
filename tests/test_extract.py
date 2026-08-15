from claimverify.extract import (
    extract_claims,
    parse_references,
    split_sections,
    split_sentences,
)

BODY = (
    "Human resource development in the region has grown quickly (Crocco, 2018). "
    "Garavan et al. (2019) argue that training transfer depends on context. "
    "Earlier work found participation rates near 40% (Smith & Jones, 2020; Lee, 2017a). "
    "This is background with no citation at all. "
    "Motivation matters (see also Deci, 1971, as cited in Ryan, 2000). "
    "The effect was significant (p < .05) in both waves."
)


def test_parenthetical_and_narrative_citations():
    claims = extract_claims(BODY)
    keys = {k.key for c in claims for k in c.cites}
    assert {
        "crocco-2018",
        "garavan-2019",
        "smith-2020",
        "lee-2017a",
        "deci-1971",
        "ryan-2000",
    } <= keys


def test_stats_parens_are_not_citations():
    claims = extract_claims("The effect was significant (p < .05) in both waves.")
    assert claims == []


def test_secondary_citation_flagged():
    claims = extract_claims(BODY)
    secondary = [c for c in claims if c.secondary]
    assert len(secondary) == 1
    assert any(k.key == "ryan-2000" for k in secondary[0].cites)


def test_context_includes_neighbours():
    claims = extract_claims(BODY)
    first = claims[0]
    assert "Garavan" in first.context


def test_sentence_split_protects_abbreviations():
    sents = split_sentences("Garavan et al. (2019) show X. A second sentence.")
    assert len(sents) == 2
    assert sents[0].startswith("Garavan et al. (2019)")


def test_split_sections_takes_last_references_heading():
    text = (
        "Intro mentions references\nReferences\nCrocco, O. S. (2018). Title. Journal."
    )
    body, refs = split_sections(text)
    assert "Crocco, O. S." in refs
    assert "Intro" in body


def test_parse_references_entries_and_keys():
    refs = parse_references(
        "Crocco, O. S. (2018). Regional HRD. HRDI, 21(2), 1-20.\n"
        "Garavan, T., McCarthy, A., & Carbery, R. (2019).\n"
        "  Training transfer. Journal of Things, 3(1), 5-25.\n"
        "World Bank. (2020). Development report. World Bank.\n"
    )
    keys = {r.key for r in refs}
    assert keys == {"crocco-2018", "garavan-2019", "world-2020"}
    garavan = next(r for r in refs if r.key == "garavan-2019")
    assert "Training transfer" in garavan.entry


def test_co_authors_and_et_al_captured():
    claims = extract_claims(
        "One idea (Crocco & Grenier, 2021). Crocco et al. (2022) found another."
    )
    paren = claims[0].cites[0]
    assert (paren.surname, paren.co_authors, paren.et_al) == (
        "Crocco",
        ("Grenier",),
        False,
    )
    narrative = claims[1].cites[0]
    assert (narrative.surname, narrative.et_al) == ("Crocco", True)
