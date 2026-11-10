"""Ovals: a foundation chain worked round both ends, out along one side and back along the other.

Engine unit cases, the guards, and whole-pipeline runs on the real engine with every model reply mocked (no API
calls; caches go to tmp_path). The made-up ovals are one in sc and one in hdc; the FACE PLATE is a real pattern's.
"""

import json
import re

import pytest

from frogless.engine import get_engine
from frogless.patterns.placement import says_other_side
from frogless.pipeline import faithful, ledger, reconcile, review, translate
from frogless.pipeline.check import check_pattern
from frogless.pipeline.guards import goes_back, oval_problem, reading_problem
from frogless.pipeline.report import RowResult
from frogless.pipeline.review import Entry, vet

E = get_engine()

FOUNDATION = "ch.A,12ch"
FACE_ROW1 = "sk,11sc,sc3inc,(10sc,sc2inc)@A"
FACE_STRAIGHT = "sk,11sc,sc3inc,10sc,sc2inc"  # the same stitches in one straight run: 24 of a 13-chain
FACE = [FOUNDATION, FACE_ROW1, "sc2inc,10sc,3*[sc2inc],10sc,2*[sc2inc]",
        "sc,sc2inc,10sc,3*[sc,sc2inc],10sc,2*[sc,sc2inc]", "2sc,sc2inc,10sc,3*[2sc,sc2inc],10sc,2*[2sc,sc2inc]"]
FACE_PIECE = """Ch 13
Row 1: sc, 10 sc, 3 sc in last, rotate, 10 sc, inc [26]
Row 2: inc, 10 sc, inc x3, 10 sc, inc x2 [32]
Row 3: sc, inc, 10 sc, (sc, inc) x3, 10 sc, (sc, inc) x2 [38]
Row 4: 2 sc, inc, 10 sc, (2 sc, inc) x3, 10 sc, (2 sc, inc) x2 [44]"""

SC_OVAL = """Ch 9
Row 1: sc in 2nd ch from hook, sc in next 6 ch, 3 sc in last ch, rotate, sc in next 6 ch on the other side, 2 sc in last ch (18)
Row 2: sc in each st around (18)
Row 3: 2 sc in each st around (36)"""
SC_OVAL_CODE = ["9ch", "sk,7sc,sc3inc,(6sc,sc2inc)@A", "18sc", "18*[sc2inc]"]  # "9ch" is labelled by the program
HDC_OVAL_CODE = ["ch.A,10ch", "2sk,8hdc,hdc3inc,(7hdc,hdc2inc)@A", "20hdc"]


def counts(*rows):
    check = E.check("\n".join(rows))
    return check, [sum(c for t, c in r.stitch_types.items() if t not in ("ch", "ss", "sk")) for r in check.rows]


# ---- the engine reads the construction ----
def test_a_sc_oval_counts_every_round():
    check, made = counts(*FACE)
    assert check.ok and made == [0, 26, 32, 38, 44]


def test_an_hdc_oval_counts():
    check, made = counts(*HDC_OVAL_CODE)
    assert check.ok and made == [0, 20, 20]


def test_a_straight_run_of_the_same_stitches_does_not_fit_the_chain():
    check, _ = counts("13ch", FACE_STRAIGHT)
    assert not check.ok and "more stitch" in check.error.message


def test_the_first_chain_is_labelled_by_the_engine_when_the_row_works_back_into_a_label_nothing_defines():
    assert E.resolve("13ch\n" + FACE_ROW1) == "\n".join(["ch.A,12ch", FACE_ROW1])
    assert E.resolve("13ch.A\n" + FACE_ROW1) == "\n".join(["ch.A,12ch", FACE_ROW1])
    assert counts("13ch", FACE_ROW1)[0].ok
    check, made = counts(*SC_OVAL_CODE)
    assert check.ok and made == [0, 18, 18, 36]


@pytest.mark.parametrize("code", [
    "13ch\n" + FACE_STRAIGHT,  # no group worked into a label
    "ring.R0\n(6sc)@R0\n(6sc)@R0",  # a ring is no foundation chain
    "13ch.B\n(2sc)@A",  # the chain carries another label
    "ch.A,12ch\n" + FACE_ROW1,  # already labelled
    "1ch\n(2sc)@A",
])
def test_code_that_is_not_an_oval_is_not_touched(code):
    assert E.resolve(code) == code


# ---- the code reads back as English that shows the way back ----
def test_the_way_back_is_said_in_the_english():
    oval = E.describe("\n".join(FACE[:3]))
    assert oval[0] == "Ch 13."
    assert oval[1] == ("Row 1: skip next ch, sc in next 11 ch, 3 sc in next ch, rotate, then work along the other side "
                       "of the foundation chain (sc in next 10 ch, 2 sc in next ch).")
    straight = E.describe("13ch\n" + FACE_STRAIGHT)
    assert "other side" not in straight[1] and "rotate" not in straight[1]
    assert E.describe("13ch\n" + FACE_ROW1) == oval[:2]  # the label is added for the reading


# ---- the guards ----
@pytest.mark.parametrize("text,yes", [
    ("R1 sc, 10 sc, 3 sc in last, rotate, 10 sc, inc [26]", True),
    ("Row 1: 2 sc in last ch, then sc along the other side of the foundation chain", True),
    ("sc in the opposite side of the chain", True),
    ("Row 1: sc in each st across, turn", False),
    ("Round 2: 2 sc in each st around", False),
])
def test_rows_that_go_back_along_the_chain_are_recognised_by_their_words(text, yes):
    assert says_other_side(text) is yes


def test_goes_back_tells_an_oval_from_a_straight_run():
    assert goes_back(E, FOUNDATION, FACE_ROW1)
    assert not goes_back(E, "13ch", "sk,11sc,sc3inc")  # the 3 sc of one increase share their chain
    assert not goes_back(E, "13ch", "sk,11sc,sc3inc,sc")
    assert not goes_back(E, "ring.R0\n(6sc)@R0", "6sc2inc")
    assert not goes_back(E, FOUNDATION, "")


def test_a_straight_row_that_says_rotate_is_a_problem_and_an_oval_is_not():
    words = "R1 sc, 10 sc, 3 sc in last, rotate, 10 sc, inc [26]"
    assert "other side of the foundation chain" in oval_problem(E, "13ch", FACE_STRAIGHT, words)
    assert oval_problem(E, FOUNDATION, FACE_ROW1, words) == ""
    assert oval_problem(E, "13ch", FACE_STRAIGHT, "R1 sc, 10 sc, 3 sc in last, 10 sc, inc [26]") == ""  # says nothing
    assert oval_problem(E, "13ch", "", words) == ""
    assert oval_problem(E, "ring.R0\n(6sc)@R0", "6sc2inc", "rotate") == ""  # no foundation chain here


def test_the_oval_reading_does_not_move_the_stitches_of_the_straight_literal():
    words = "R1 sc, 10 sc, 3 sc in last, rotate, 10 sc, inc [26]"
    assert reading_problem(E, FOUNDATION, FACE_STRAIGHT, FACE_ROW1, words) == ""
    # without the words about the other side the same change is refused
    assert "moves the stitches" in reading_problem(E, FOUNDATION, FACE_STRAIGHT, FACE_ROW1,
                                                   "R1 sc in next 11 ch, 3 sc in last, sc in next 10 ch, inc [26]")


def test_the_ledger_lets_an_oval_work_into_the_chain_twice():
    row = "R1 sc, 10 sc, 3 sc in last, rotate, 10 sc, inc [26]"
    assert ledger._uses_fit(row, 24, [9, 10, 11, 12, 13])
    assert not ledger._uses_fit("R1 sc, 10 sc, 3 sc in last, 10 sc, inc [26]", 24, [9, 10, 11, 12, 13])
    assert not ledger._uses_fit(row, 30, [9, 10, 11, 12, 13])


def test_a_fix_of_the_foundation_chain_of_an_oval_is_refused():
    rows = [RowResult(index=0, source="Ch 13", code="13ch"),
            RowResult(index=1, source="R1 sc, 10 sc, 3 sc in last, rotate, 10 sc, inc [26]", code=FACE_STRAIGHT)]
    fix = Entry(0, "Ch 13", "fix", "same", "too short", fixed_text="Ch 24")
    kept, reasons = vet("bob", rows, [fix])
    assert not kept and "foundation chain of an oval" in reasons[0]
    plain = [rows[0], RowResult(index=1, source="R1 sc in each ch across", code="sk,11sc")]
    assert vet("bob", plain, [fix])[0] == [fix]


# ---- whole pipeline, model mocked ----
class Mock:
    """A fake chat(): translate_row answers by row number from `codes`; the checker is generous (only the program's
    own checks stand in the way); the reviewer says what it is told."""

    def __init__(self, codes, alice=(), bob=()):
        self.codes, self.alice, self.bob = codes, list(alice), list(bob)
        self.prompts = []

    def __call__(self, role, messages, **opts):
        prompt, name = messages[0]["content"], opts.get("prompt_cache_key", "").split("-")[0]
        self.prompts.append((name, prompt))
        if name == "translate_row":
            index = int(re.search(r"Translate row (\d+) now", prompt).group(1))
            body = {"code": self.codes[index]}
        elif name == "faithful_row":
            body = {"verdict": "faithful", "reading": "", "reason": ""}
        elif name == "review":
            side = self.alice if "Your side: ALICE" in prompt else self.bob
            body = {"summary": "my case", "rows": side[0] if side else []}
        elif name == "reconcile_row":
            body = {"code": "", "explanation": "no other reading"}
        elif name == "ledger_row":
            body = {"uses": 24, "makes": 26, "skips": 0, "quotes": ["rotate"], "explanation": "11 + 3 + 10 + 2 = 26"}
        else:
            raise AssertionError(f"unexpected model call: {name}")
        return {"text": json.dumps(body), "usage": {"input_tokens": 1, "output_tokens": 1}, "cost_usd": 0.0}

    def calls(self, name):
        return [p for n, p in self.prompts if n == name]


def run(monkeypatch, tmp_path, text, mock, **kw):
    real = translate.ask_cached

    def ask(prompt, role, schema, cache_dir, name):
        return real(prompt, role, schema, tmp_path / name, name)

    monkeypatch.setattr(translate, "chat", mock)
    for module in (translate, faithful, reconcile, review, ledger):
        monkeypatch.setattr(module, "ask_cached", ask)
    return check_pattern(text, **kw)


def entry(row, quote, verdict, **kw):
    base = {"row": row, "quote": quote, "verdict": verdict, "code": "same", "explanation": "x", "fixed_text": "",
            "insert_after": -1, "inserted_text": "", "inserted_code": ""}
    return {**base, **kw}


def test_the_face_plate_works(monkeypatch, tmp_path):
    mock = Mock(["13ch"] + FACE[1:])  # the model reads the oval; row 0 is the rules' own
    report = run(monkeypatch, tmp_path, FACE_PIECE, mock)
    assert report.verdict.kind == "works", report.verdict
    assert report.rows[1].code == FACE_ROW1 and report.rows[1].faithful
    assert "other side of the foundation chain" in report.rows[1].english
    assert report.stated == {1: 26, 2: 32, 3: 38, 4: 44} and report.computed == report.stated


def test_a_straight_translation_of_an_oval_row_is_never_a_break_of_the_chain(monkeypatch, tmp_path):
    # the model never learns the oval: every attempt is the straight run (24 stitches on a 13-chain)
    mock = Mock(["13ch", FACE_STRAIGHT] + FACE[2:], bob=[[entry(0, "Ch 13", "fix", fixed_text="Ch 24", code="24ch")]])
    report = run(monkeypatch, tmp_path, FACE_PIECE, mock)
    v = report.verdict
    assert not (v.kind == "breaks" and v.row == 0)
    assert not any(f.row == 0 for f in v.fixes)
    assert report.rows[1].code != FACE_STRAIGHT  # the straight run was refused ...
    assert report.rows[1].status == "cannot"  # ... and the row is counted, not charted
    assert any("other side of the foundation chain" in p for p in mock.calls("translate_row"))  # told why, on the retry
