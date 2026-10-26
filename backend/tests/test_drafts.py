from datetime import date

import pytest

from app.drafts import textutils as tu
from app.drafts.engine import ValidationError
from app.drafts.render import to_docx, to_text
from app.drafts.templates import TEMPLATES


@pytest.mark.parametrize("n,words", [
    (0, "Zero"),
    (15, "Fifteen"),
    (100000, "One Lakh"),
    (885000, "Eight Lakh Eighty Five Thousand"),
    (12500000, "One Crore Twenty Five Lakh"),
    (1000000000, "One Hundred Crore"),
])
def test_indian_words(n, words):
    assert tu.int_to_words_indian(n) == words


def test_rupees_and_grouping():
    assert tu.group_indian(1250000) == "12,50,000"
    assert tu.group_indian(999) == "999"
    assert tu.rupees("1250000.5") == "Rs. 12,50,000.50/- (Rupees Twelve Lakh Fifty Thousand and Paise Fifty Only)"


def test_dates_and_grammar():
    assert tu.long_date(date(2026, 10, 1)) == "1st day of October, 2026"
    assert tu.long_date(date(2026, 10, 13)) == "13th day of October, 2026"
    assert tu.join_names(["A", "B", "C"]) == "A, B and C"
    assert tu.role("Defendant", 2) == "Defendants"


def test_that_clause_keeps_proper_nouns():
    assert tu.that_clause("The defendant failed to pay.") == "That the defendant failed to pay."
    assert tu.that_clause("ABC Traders supplied goods.") == "That ABC Traders supplied goods."
    assert tu.that_clause("I am the deponent.") == "That I am the deponent."
    assert tu.that_clause("that it is so.") == "That it is so."


def test_paragraphs_strip_user_numbering():
    assert tu.paragraphs("1. First\n\n2) Second\n- Third") == ["First", "Second", "Third"]


@pytest.mark.parametrize("tid", list(TEMPLATES))
def test_every_sample_renders(tid):
    t = TEMPLATES[tid]
    draft = t.generate(t.sample)
    text = to_text(draft)
    assert len(draft.blocks) > 5
    assert "1. That" in text  # numbered body paragraphs present
    assert ".." not in text.replace("...", "")  # no doubled periods
    assert to_docx(draft)[:2] == b"PK"  # a real zip/docx


def test_validation_collects_all_errors():
    with pytest.raises(ValidationError) as e:
        TEMPLATES["legal_notice"].generate({"amount_due": "abc"})
    errs = e.value.errors
    assert "client_name" in errs and "recipients" in errs
    assert errs["amount_due"] == "Amount due (Rs.) must be a number."


def test_plural_parties_and_joint_liability():
    t = TEMPLATES["recovery_suit"]
    data = dict(t.sample, defendants=[{"name": "X"}, {"name": "Y"}])
    text = to_text(t.generate(data))
    assert "...DEFENDANT NO. 2" in text
    assert "the Defendants are X and Y" in text
    assert "jointly and severally" in text


def test_limitation_warning():
    t = TEMPLATES["recovery_suit"]
    draft = t.generate(dict(t.sample, cause_of_action_date="2019-01-01", date="2026-10-27"))
    assert any("3-year limitation" in w for w in draft.warnings)


def test_bail_custody_days():
    t = TEMPLATES["bail_application"]
    draft = t.generate(dict(t.sample, arrest_date="2026-10-01", date="2026-10-27", chargesheet="Filed"))
    assert "for 26 days as on date" in to_text(draft).replace("\n", " ").replace("   ", " ")
    assert not any("default bail" in w for w in draft.warnings)
