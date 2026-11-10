"""A square worked in rounds from a chain ring: the last side of a round that starts in a corner space wraps back
onto the stitches before the round below's first chain (real engine; the model is mocked, no API calls)."""

import json

import pytest

from frogless.engine import get_engine
from frogless.pipeline import translate
from frogless.pipeline.report import PatternReport, RowResult
from frogless.pipeline.review import review_report
from frogless.pipeline.verdict import decide_verdict

RING = "(4ch,ss@[%,0]).R_1"
R1 = "(dc.S,2ch.A,3dc,2ch.B,3dc,2ch.C,3dc,2ch.D,2dc)@R_1,ss@S"
R2_PLAIN = "(dc.W,2ch.E,2dc)@A,3dc,(2dc,2ch.F,2dc)@B,3dc,(2dc,2ch.G,2dc)@C,3dc,(2dc,2ch.H,2dc)@D,3dc,dc@A,ss"
R2_WRAPPED = "(dc.W,2ch.E,2dc)@A,3dc,(2dc,2ch.F,2dc)@B,3dc,(2dc,2ch.G,2dc)@C,3dc,(2dc,2ch.H,2dc)@D,2dc,dc@S,dc@A,ss"
R2_LITERAL = R2_PLAIN.replace("3dc", "7dc")  # every side number as the words give it
R3_PLAIN = "(dc.V,2ch.I,2dc)@E,7dc,(2dc,2ch.J,2dc)@F,7dc,(2dc,2ch.K,2dc)@G,7dc,(2dc,2ch.L,2dc)@H,7dc,dc@E,ss"
R3_LITERAL = R3_PLAIN.replace("7dc", "11dc")

TEXT = """Make a ring of 4 chains, join with a slip stitch.
Round 1: Ch 5 (counts as dc and ch 2), [3 dc into ring, ch 2] 3 times, 2 dc into ring, slst to the first chain. (12 dc)
Round 2: Slst into the ch-2 space, ch 5, 2 dc in same space, 7dc, (2dc, ch 2, 2dc, 7dc) 3 times, dc in last corner, slst. (28 dc)
Round 3: Slst into the ch-2 space, ch 5, 2 dc in same space, 11dc, (2dc, ch 2, 2dc, 11dc) 3 times, dc in last corner, slst. (44 dc)"""
SOURCES = TEXT.splitlines()


@pytest.fixture(scope="module")
def engine():
    return get_engine()


def complete_wraps(code):
    return get_engine().resolve(code)


def counts(engine, *rows):
    check = engine.check("\n".join(rows))
    return check, [r.stitch_types.get("dc") for r in check.rows]


def test_a_side_written_plain_wraps_onto_the_stitches_before_the_first_chain(engine):
    check, dc = counts(engine, RING, R1, R2_PLAIN, R3_PLAIN)
    assert check.ok and dc[1:] == [12, 28, 44]
    assert all(r.unworked == 0 and r.overflow == 0 for r in check.rows)


def test_the_wrap_is_the_same_as_writing_it_out(engine):
    assert counts(engine, RING, R1, R2_WRAPPED)[1] == counts(engine, RING, R1, R2_PLAIN)[1]
    assert complete_wraps("\n".join([RING, R1, R2_PLAIN])).splitlines()[2].endswith("2dc,dc@S,dc@A,ss")
    assert engine.resolve("\n".join([RING, R1, R2_PLAIN])).splitlines()[2].count("@S") == 1
    assert engine.resolve("\n".join([RING, R1, R2_PLAIN])).splitlines()[0] == RING


def test_a_stitch_label_is_added_when_the_row_below_has_none(engine):
    r1 = R1.replace("dc.S", "dc").replace(",ss@S", ",ss")
    wrapped = complete_wraps("\n".join([RING, r1, R2_PLAIN])).splitlines()
    assert ".W1" in wrapped[1] and wrapped[2].endswith("dc@W1,dc@A,ss")
    assert counts(engine, RING, r1, R2_PLAIN)[1][1:] == [12, 28]


def test_a_run_that_does_not_reach_back_or_overshoots_is_left_alone(engine):
    short = R2_PLAIN.replace("@D,3dc,", "@D,2dc,")  # stops before the wrap: the engine says a stitch is left
    over = R2_PLAIN.replace("@D,3dc,", "@D,4dc,")  # more than the stitches that remain and the ones before the first chain
    split = R2_PLAIN.replace("@D,3dc,", "@D,3dc,dc,")  # a longer run, two items long, is not rewritten
    for code in (short, over, split):
        assert complete_wraps("\n".join([RING, R1, code])) == "\n".join([RING, R1, code])
    assert not engine.check("\n".join([RING, R1, short])).ok


def test_code_that_is_not_a_corner_round_is_not_touched():
    for code in ("ring.R0\n(12sc)@R0\n12*[sc2inc]", "(4ch,ss@[%,0]).R_1\n" + R1.replace("ss@S", "ss"),
                 "20ch\n18dc,turn\n18dc"):
        assert complete_wraps(code) == code


# ---- the review: Alice's side-total reading of Round 2 and 3 is allowed, and the pattern works ----
def rows_as_translated():
    codes = [RING, R1, R2_LITERAL, R3_LITERAL]
    return [RowResult(index=i, source=s, code=c, origin="rules" if i == 0 else "model", faithful=True)
            for i, (s, c) in enumerate(zip(SOURCES, codes))]


class Script:
    def __init__(self, alice):
        self.alice, self.prompts = alice, []

    def __call__(self, role, messages, **opts):
        prompt = messages[0]["content"]
        self.prompts.append(prompt)
        if "Your side: ALICE" in prompt:
            body = {"summary": "the numbers beside the sides are side totals", "rows": self.alice}
        elif "Your side: BOB" in prompt:
            body = {"summary": "nothing to fix", "rows": []}
        elif "reviewer read this row" in prompt:
            body = {"verdict": "interpreted", "reading": "7dc is the whole side, corners included", "reason": "unclear"}
        else:
            body = {"verdict": "faithful", "reading": "", "reason": ""}
        return {"text": json.dumps(body), "usage": {"input_tokens": 1, "output_tokens": 1}, "cost_usd": 0.0}


def entry(row, quote, code):
    return {"row": row, "quote": quote, "verdict": "reading", "code": code, "fixed_text": "",
            "explanation": "7dc counts the corner stitches, so 3 plain dc sit between the corners"}


def test_the_side_totals_of_a_square_from_a_chain_ring_work(engine, monkeypatch, tmp_path):
    rows = rows_as_translated()
    check = engine.check("\n".join(r.code for r in rows))
    verdict, stated, computed = decide_verdict(engine, TEXT, rows, check)
    assert verdict.kind == "breaks" and verdict.row == 2  # as written: 7 dc between the corners makes 44, not 28
    report = PatternReport(text=TEXT, rows=rows, check=check, verdict=verdict, stated=stated, computed=computed)
    script = Script([entry(2, "7dc", R2_WRAPPED), entry(3, "11dc", R3_PLAIN)])
    monkeypatch.setattr(translate, "chat", script)
    review_report(engine, TEXT, report, cache_dir=tmp_path / "review", faithful_cache_dir=tmp_path / "faithful")
    assert report.review.outcome == "works_with_readings" and report.review.alice_passed
    assert report.verdict.kind == "works", report.verdict.message
    assert [report.computed[n] for n in (1, 2, 3)] == [12, 28, 44]
    assert not any("not allowed as a reading" in p for p in script.prompts)
