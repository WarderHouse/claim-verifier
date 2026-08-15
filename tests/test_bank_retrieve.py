from pathlib import Path

from claimverify.bank import SourceBank, _chunk
from claimverify.extract import CiteKey
from claimverify.retrieve import rank


def make_bank(tmp_path: Path) -> SourceBank:
    (tmp_path / "Crocco and Zarestky-2024.txt").write_text(
        "Training participation in Southeast Asia varies widely by sector.\n\n"
        + ("Filler paragraph about unrelated matters. " * 30 + "\n\n") * 3
        + "We found that womens participation in employer training lagged mens by nine points.",
        encoding="utf-8",
    )
    (tmp_path / "notes.docx").write_text("ignored", encoding="utf-8")
    return SourceBank(tmp_path)


def test_filename_keys(tmp_path):
    bank = make_bank(tmp_path)
    assert bank.lookup(CiteKey("Crocco", "2024")) is not None
    assert bank.lookup(CiteKey("Zarestky", "2024")) is None  # first author only


def test_year_suffix_insensitive_lookup(tmp_path):
    bank = make_bank(tmp_path)
    assert bank.lookup(CiteKey("Crocco", "2024a")) is not None


def test_co_authors_break_same_year_ties(tmp_path):
    (tmp_path / "Crocco and Grenier-2021.txt").write_text(
        "grenier text", encoding="utf-8"
    )
    (tmp_path / "Crocco and Cseh-2021.txt").write_text("cseh text", encoding="utf-8")
    (tmp_path / "Crocco et al.-2021.txt").write_text("etal text", encoding="utf-8")
    (tmp_path / "Crocco-2021.txt").write_text("solo text", encoding="utf-8")
    bank = SourceBank(tmp_path)
    assert (
        bank.lookup(CiteKey("Crocco", "2021", ("Grenier",))).path.name
        == "Crocco and Grenier-2021.txt"
    )
    assert (
        bank.lookup(CiteKey("Crocco", "2021", ("Cseh",))).path.name
        == "Crocco and Cseh-2021.txt"
    )
    assert (
        bank.lookup(CiteKey("Crocco", "2021", (), et_al=True)).path.name
        == "Crocco et al.-2021.txt"
    )
    assert bank.lookup(CiteKey("Crocco", "2021")).path.name == "Crocco-2021.txt"


def test_zero_score_match_signals_caution(tmp_path):
    (tmp_path / "Crocco-2023.txt").write_text("a different solo work", encoding="utf-8")
    bank = SourceBank(tmp_path)
    match = bank.lookup(CiteKey("Crocco", "2023", ("Rockett",)))
    assert match.path.name == "Crocco-2023.txt"
    assert match.score == 0  # cited work absent; caller must surface the caution
    assert bank.lookup(CiteKey("Crocco", "2023")).score > 0


def test_unknown_key_returns_none_not_error(tmp_path):
    bank = make_bank(tmp_path)
    assert bank.lookup(CiteKey("Garavan", "2019")) is None
    assert bank.passages_for(None) == []


def test_chunking_bounds():
    text = "\n\n".join(["word " * 200, "word " * 10, "word " * 150])
    chunks = _chunk(text, "x.txt")
    assert all(len(c.text.split()) <= 400 for c in chunks)
    assert sum(len(c.text.split()) for c in chunks) == 360


def test_bm25_ranks_topical_passage_first(tmp_path):
    bank = make_bank(tmp_path)
    passages = bank.passages_for(bank.lookup(CiteKey("Crocco", "2024")).path)
    top = rank("women's participation in employer training lagged", passages, top_k=2)
    assert "womens participation" in top[0].text
