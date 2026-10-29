"""The guards on readings: no deleting, no moving explicitly placed stitches (real engine, no model calls)."""

import pytest

from frogless.engine import get_engine
from frogless.patterns.placement import bare_number, named_families, states_placement
from frogless.pipeline.guards import reading_problem

RING = "ring.R0\n(12sc)@R0"  # a 12-stitch round to work into
SQUARE_ROW = "(dc.V,2ch.I,2dc)@E,7dc,(2dc,2ch.J,2dc)@F,7dc,dc"  # shape only; needs earlier rows to check


@pytest.fixture(scope="module")
def engine():
    return get_engine()


# ---- the engine's comparison ----
def test_row_items_list_what_the_code_writes(engine):
    items = engine.row_items("2ch.A,7dc,3*[sc,sc2inc]@R0,ss")
    assert [(i.kind, i.count, i.times) for i in items] == [
        ("ch", 2, 1), ("dc", 7, 1), ("sc", 1, 3), ("sc2inc", 1, 3), ("ss", 1, 1)]
    assert engine.row_items("ring.R0") == []


def test_removing_an_item_is_a_drop(engine):
    assert engine.reading_drops_items("6*[sc,sc2inc],sc", "6*[sc,sc2inc]", RING)
    assert engine.reading_drops_items("3ch,5dc", "5dc", RING)  # the chain is gone


def test_changing_a_number_is_not_a_drop(engine):
    assert not engine.reading_drops_items("7dc,ch,7dc", "3dc,ch,3dc", RING)
    assert not engine.reading_drops_items("6*[sc,sc2inc]", "6*[sc,sc2inc]", RING)


def test_a_stitch_type_the_text_names_must_not_disappear(engine):
    assert engine.reading_drops_items("", "6*[sc2inc]", "", named=("sc", "ch"))  # no literal: the text's names count
    assert not engine.reading_drops_items("", "ch,6*[sc2inc]", "", named=("sc", "ch"))
    assert engine.reading_drops_items("ch,6sc", "12sc", RING, named=("ch",))
    # a stitch the literal code never worked is not required of the reading
    assert not engine.reading_drops_items("12sc", "6*[sc2inc]", RING, named=("ch",))


def test_compare_readings_reports_consumption_and_number_changes(engine):
    diff = engine.compare_readings("12*[2dc,dc2inc]", "12*[dc,dc2inc]", "ring.R0\n(12sc)@R0\n12*[sc2inc]")
    assert diff.same_shape and diff.number_changes == [("dc", 2, 1)] and diff.consumes == (36, 24)


# ---- the text's side ----
def test_the_text_names_stitches_and_places():
    assert named_families("Rnd 3: sc in next 2 sts, ch 1, slst to join") == ("sc", "ch", "ss")
    assert named_families("double crochet in each stitch") == ("dc",)
    assert states_placement("(dc in next 2 sts, dc inc) 12 times (48)")
    assert states_placement("2 dc in same st") and states_placement("dc in each ch-sp")
    assert not states_placement("dc across (24)")


def test_a_bare_number_sits_beside_the_stitch_not_beside_next():
    assert bare_number("slst in ch2 space, 7dc, (2dc, ch2, 2dc, 7dc) 3 times", 7, "dc")
    assert bare_number("sc 11 along each side", 11, "sc") is False  # the stitch must follow the number
    assert not bare_number("dc in next 2 sts", 2, "dc")  # "2 sts" is not a stitch name
    assert not bare_number("dc in next 7 dc", 7, "dc")  # a place to work, not a length


# ---- reading_problem ----
CIRCLE = "ring.R0\n(12sc)@R0"
SQUARE = ("ring.R0\n(dc.S,2ch.A,3dc,2ch.B,3dc,2ch.C,3dc,4ch.D,2dc)@R0,ss@S\n"  # not a real square, only labelled spaces
          "(dc.W,2ch.E,2dc)@A,3dc,(2dc,2ch.F,2dc)@B,3dc,(2dc,2ch.G,2dc)@C,3dc,(2dc,2ch.H,2dc)@D,3dc,dc,ss@W")


def test_a_reading_that_deletes_a_planted_stitch_is_rejected(engine):
    source = "Rnd 3: (sc, 2 sc in next st) 6 times, sc (18)"
    why = reading_problem(engine, CIRCLE, "6*[sc,sc2inc],sc", "6*[sc,sc2inc]", source)
    assert "drops" in why


def test_a_reading_that_changes_only_a_number_between_corners_is_allowed(engine):
    source = "Rnd 4: slst in ch2 space, 11dc, (2dc, ch2, 2dc, 11dc) 3 times in each corner, dc in last corner"
    before = "ring.R0\n(12sc)@R0"
    literal = "7dc,(2dc,2ch,2dc),7dc"
    reading = "3dc,(2dc,2ch,2dc),3dc"
    assert reading_problem(engine, "", literal, reading, source) == ""  # compared structurally; still no verdict on counts
    assert reading_problem(engine, before, literal, reading, "7dc, (2dc, ch2, 2dc, 7dc) 3 times in each corner") == ""


def test_the_side_total_case_is_allowed_even_though_the_stitches_it_works_into_change(engine):
    # row below: 12 sc. Literal "7dc" between corners works into 7 + ...; the reading works into fewer.
    before = CIRCLE
    literal = "(2dc,2ch,2dc),7dc,(2dc,2ch,2dc)"  # 4+7+4 = 15 stitches... only the consumption matters here
    reading = "(2dc,2ch,2dc),3dc,(2dc,2ch,2dc)"
    diff = engine.compare_readings(literal, reading, before)
    assert diff.consumes[0] != diff.consumes[1] and diff.same_shape
    source = "Rnd 2: (2dc, ch2, 2dc), 7dc, (2dc, ch2, 2dc) 3 times in each corner"
    assert reading_problem(engine, before, literal, reading, source) == ""
    # the same change is refused when the 7 is written as a place to work
    source = "Rnd 2: (2dc, ch2, 2dc) in each corner, dc in next 7 dc"
    assert "moves the stitches" in reading_problem(engine, before, literal, reading, source)


def test_a_reading_that_changes_where_stitches_go_is_rejected(engine):
    before = "ring.R0\n(12sc)@R0\n12*[sc2inc]"  # 24 stitches
    source = "Round 3: (dc in next 2 sts, dc inc) 12 times (48)"
    why = reading_problem(engine, before, "12*[2dc,dc2inc]", "12*[dc,dc2inc]", source)
    assert "moves the stitches" in why and "24" in why and "36" in why


def test_unchanged_code_raises_no_objection_and_an_empty_reading_is_a_drop(engine):
    assert reading_problem(engine, CIRCLE, "12sc", "12sc", "Round 2: sc in each st (12)") == ""
    assert "drops" in reading_problem(engine, CIRCLE, "12sc", "", "Round 2: sc in each st (12)")


def test_an_engine_that_cannot_list_items_gives_no_verdict():
    from frogless.engine.base import Engine

    class Blind(Engine):  # row_items stays None
        pass

    Blind.__abstractmethods__ = frozenset()
    assert reading_problem(Blind(), "", "12sc", "6sc", "Round 2: sc in each st (12)") == ""


# ---- a phrase the row writes twice in a row ----
TWICE = "Round 2: slst in ch2 space, ch3, 2dc in same space. Ch3, 2dc in same space. 5dc, dc in last corner (14dc)"
ONCE_CODE = "(dc.W,2ch.E,2dc)@A,5dc,dc,ss@W"  # the translator merged the two copies
TWICE_CODE = "(dc.W,2ch.E,2dc,dc,2ch.F,2dc)@A,5dc,dc,ss@W"


def test_a_phrase_written_twice_in_a_row_is_found():
    from frogless.patterns.placement import repeated_phrases

    assert repeated_phrases(TWICE) == ["Ch3, 2dc in same space"]
    assert repeated_phrases("Round 2: sc in each st, ch 1, turn (12)") == []
    assert repeated_phrases("Round 2: [ch 3, 2dc in same space] x2, 5dc") == []  # a multiplier is not a repeat of text
    assert repeated_phrases("Round 2: sc, sc, sc, 5dc") == []  # one piece twice is just two stitches


def test_a_reading_that_drops_the_repeated_phrase_is_refused_once_the_literal_code_keeps_it(engine):
    before = SQUARE.split("\n(dc.W")[0]
    why = reading_problem(engine, before, TWICE_CODE, ONCE_CODE, TWICE)
    assert "drops" in why
    assert reading_problem(engine, before, TWICE_CODE, TWICE_CODE.replace("5dc", "3dc"), "Round 2: 5dc, dc") == ""  # a number is fine


def test_a_translation_that_merged_the_repeated_phrase_is_asked_again_and_replaced(engine, monkeypatch, tmp_path):
    import json

    from frogless.pipeline import translate
    from frogless.pipeline.faithful import restore_repeats
    from frogless.pipeline.report import RowResult

    asked = []

    def fake_chat(role, messages, **opts):
        asked.append(messages[0]["content"])
        return {"text": json.dumps({"code": TWICE_CODE}), "usage": {"output_tokens": 5}, "cost_usd": 0.01}

    monkeypatch.setattr(translate, "chat", fake_chat)
    before = SQUARE.split("\n(dc.W")[0]
    rows = [RowResult(index=0, source="Round 1: x", code=before, origin="rules"),
            RowResult(index=1, source=TWICE, code=ONCE_CODE, origin="model")]
    row, cost = restore_repeats(engine, "Round 1: x\n" + TWICE, rows, 1, tmp_path)
    assert row.code == TWICE_CODE and cost == 0.01
    assert 'the row writes "Ch3, 2dc in same space" twice in a row' in asked[0]
    # a reply that does not add anything (or a row without a repeated phrase) leaves the code alone
    plain = RowResult(index=1, source="Round 2: 5dc, dc", code="5dc,dc", origin="model")
    assert restore_repeats(engine, "x", [rows[0], plain], 1, tmp_path) == (plain, 0.0)
    monkeypatch.setattr(translate, "chat", lambda *a, **k: {"text": json.dumps({"code": ONCE_CODE}),
                                                            "usage": {"output_tokens": 5}, "cost_usd": 0.0})
    kept, _ = restore_repeats(engine, "y\n" + TWICE, rows, 1, tmp_path / "other")
    assert kept.code == ONCE_CODE
