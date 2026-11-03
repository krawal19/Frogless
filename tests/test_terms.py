"""US/UK detection and UK -> US conversion."""

import pytest

from frogless.patterns.terms import detect_terms, to_us
from frogless.pipeline.check import check_pattern


@pytest.mark.parametrize("text,kind,other", [
    ("Written in US terms.\nRound 1: 6 dc in ring", "US", "2 htr"),
    ("UK terms used throughout. Round 1: 6 dc", "UK", "6 sc"),
    ("Pattern uses American terminology. 6 dc", "US", "2 htr"),
    ("British crochet terms. 6 dc", "UK", "6 sc"),
    ("Abbreviations (UK): dc, tr", "UK", "6 sc"),
])
def test_stated_note_wins(text, kind, other):
    assert detect_terms(text).kind == kind
    assert detect_terms(text + "\n" + other).kind == kind  # even against a strong signal


def test_stated_note_in_evidence():
    assert detect_terms("UK terms").evidence == ['says "UK terms"']


def test_word_us_is_not_a_note():
    assert detect_terms("Give us a dc and a tr").kind == "unknown"


@pytest.mark.parametrize("text,kind,word", [
    ("Round 1: 6 sc in ring", "US", "sc"),
    ("Work a single crochet in each", "US", "single crochet"),
    ("hdc in next 3 sts", "US", "hdc"),
    ("Work a half double crochet", "US", "half double"),
    ("2 htr in next st", "UK", "htr"),
    ("Work a half treble in each", "UK", "half treble"),
    ("yoh and pull through", "UK", "yoh"),
])
def test_strong_signals(text, kind, word):
    t = detect_terms(text)
    assert t.kind == kind and not t.ambiguous
    assert any(word in e for e in t.evidence)


@pytest.mark.parametrize("text,kind", [
    ("dc in next st, miss 2 sts, tr", "UK"),
    ("Check your tension. dc, tr", "UK"),
    ("dc, skip 2 sts, tr", "US"),
    ("Gauge: 10 sts = 4 in. dc", "US"),
])
def test_medium_signals(text, kind):
    t = detect_terms(text)
    assert t.kind == kind and not t.ambiguous


def test_strong_beats_medium():
    assert detect_terms("sc, miss 2 sts").kind == "US"


def test_evidence_lists_words():
    assert detect_terms("htr in next st, miss 2").evidence == ['uses "htr"']
    assert detect_terms("dc, miss 2, tension 20 sts").evidence == ['says "miss"', 'says "tension"']


@pytest.mark.parametrize("text", [
    "6 sc, 2 htr",
    "dc, miss 2, skip 2",
    "US terms and UK terms are both given",
])
def test_conflicts_are_unknown_and_ambiguous(text):
    t = detect_terms(text)
    assert t.kind == "unknown" and t.ambiguous


@pytest.mark.parametrize("text", [
    "Round 1: ch 2, 3 dc, tr, ss to join",
    "Rnd 1: MR, Ch3, (tr,2dc)x4, Sl.st",
])
def test_only_dc_tr_is_ambiguous(text):
    t = detect_terms(text)
    assert t.kind == "unknown" and t.ambiguous and t.evidence == []


def test_nothing_to_go_on_is_not_ambiguous():
    t = detect_terms("Chain 20. Slip stitch to join.")
    assert t.kind == "unknown" and not t.ambiguous


def test_chain_height_is_not_a_signal():
    assert detect_terms("ch 3, dc in each st").kind == "unknown"


@pytest.mark.parametrize("uk,us", [
    ("dc", "sc"), ("htr", "hdc"), ("tr", "dc"), ("dtr", "tr"), ("trtr", "dtr"), ("ttr", "dtr"),
    ("miss 2 sts", "skip 2 sts"),
    ("dc2tog", "sc2tog"), ("tr3tog", "dc3tog"), ("htr2tog", "hdc2tog"),
    ("dc in next 3 sts", "sc in next 3 sts"),
    ("2 tr in next st", "2 dc in next st"),
    ("dc inc", "sc inc"), ("6dc", "6sc"), ("3tr", "3dc"), ("(2dc, tr) in next st", "(2sc, dc) in next st"),
    ("DC and Tr", "SC and Dc"),
    ("double crochet, treble crochet", "single crochet, double crochet"),
    ("half treble", "half double"),
])
def test_to_us(uk, us):
    assert to_us(uk) == us


def test_to_us_is_one_pass():
    assert to_us("dc, tr, dtr, trtr") == "sc, dc, tr, dtr"
    assert to_us("tr dc htr") == "dc sc hdc"


def test_to_us_leaves_the_rest_alone():
    for text in ["ch 12, sl st, ss in first ch", "Round 3 (42): 7 times, ch2, 12 sts, magic ring, inc, dec"]:
        assert to_us(text) == text
    assert to_us("two trs") == "two dcs"


def test_uk_pattern_is_converted_and_noted():
    report = check_pattern("Round 1: 6 dc in ring, htr (7)", use_model=False)
    assert report.terms.kind == "UK"
    assert report.notes == ['Read as UK terms (uses "htr"); converted to US.']
    assert "sc" in report.code and "hdc" in report.code


def test_ambiguous_is_checked_as_us_with_a_note():
    report = check_pattern("Round 1: 6 dc in ring (6)", use_model=False)
    assert report.terms.ambiguous
    assert any("checked as US terms" in n for n in report.notes)
    assert "dc" in report.code


def test_terms_option_forces_the_reading():
    text = "Round 1: 6 dc in ring (6)"
    uk = check_pattern(text, use_model=False, terms="UK")
    assert uk.terms.kind == "UK" and uk.notes and "sc" in uk.code and "dc" not in uk.code
    us = check_pattern(text, use_model=False, terms="US")
    assert us.terms.kind == "US" and not us.notes
    with pytest.raises(ValueError):
        check_pattern(text, use_model=False, terms="French")
