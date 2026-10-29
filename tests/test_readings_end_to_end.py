"""Planted mistakes must stay mistakes: whole-pipeline runs on the real engine with every model reply mocked.

A: an extra trailing stitch that a "reading" would simply leave out.
B: a missing round that a "reading" would paper over by moving stitches; Bob may insert it.
C: a fix of a row that already works if the turning chain counts becomes conditional.
No API calls: translate.chat is replaced; caches go to tmp_path.
"""

import json

import pytest

from frogless.pipeline import faithful, reconcile, review, translate
from frogless.pipeline.check import check_pattern
from frogless.pipeline.messages import fix_lines, user_message
from frogless.pipeline.output import clean_pattern

A = """Round 1: 6 sc in a magic ring (6)
Round 2: 2 sc in each st around (12)
Round 3: *sc, 2 sc in next st; repeat from * 6 times, sc (18)
Round 4: sc in each st around (18)"""
A_LITERAL = "6*[sc,sc2inc],sc"  # what the words say: 19 stitches
A_READING = "6*[sc,sc2inc]"  # the planted ", sc" left out

B = """Round 1: 12 sc in a magic ring (12)
Round 2: 2 sc in each st around (24)
Round 3: (dc in next 2 sts, dc inc) 12 times (48)"""
B_LITERAL = "12*[2dc,dc2inc]"  # works into 36 stitches of a 24-stitch round
B_READING = "12*[dc2inc,dc2inc]"  # makes the 48 too, but works into 24 stitches instead of 36
B_MISSING = "Round 3: (sc, 2 sc in next st) 12 times (36)"
B_MISSING_CODE = "12*[sc,sc2inc]"


class Mock:
    """A fake chat() that answers by the kind of request (the cache key's name) and keeps the prompts."""

    def __init__(self, translate_code, reading, alice=(), bob=(), judge=None):
        self.translate_code, self.reading = translate_code, reading
        self.alice, self.bob, self.judge = list(alice), list(bob), judge
        self.prompts = []

    def __call__(self, role, messages, **opts):
        prompt, name = messages[0]["content"], opts.get("prompt_cache_key", "").split("-")[0]
        self.prompts.append((name, prompt))
        if name == "translate_row":
            body = {"code": self.translate_code}
        elif name == "reconcile_row":
            body = {"code": self.reading, "explanation": "the last sc is the same as the first of the repeats"}
        elif name == "faithful_row":
            body = (self.judge or self.default_judge)(prompt)
        elif name == "review":
            side = self.alice if "Your side: ALICE" in prompt else self.bob
            body = {"summary": "my case", "rows": side[0] if side else []}
        else:
            raise AssertionError(f"unexpected model call: {name}")
        return {"text": json.dumps(body), "usage": {"input_tokens": 1, "output_tokens": 1}, "cost_usd": 0.0}

    @staticmethod
    def default_judge(prompt):
        # the checker is generous: it calls any reading "interpreted" -- only the program's guards stand in the way
        if "reviewer read this row" in prompt or "translator read it another way" in prompt:
            return {"verdict": "interpreted", "reading": "the extra stitch is a restatement", "reason": "unclear"}
        return {"verdict": "faithful", "reading": "", "reason": ""}

    def calls(self, name):
        return [p for n, p in self.prompts if n == name]


def run(monkeypatch, tmp_path, text, mock):
    """check_pattern() with the model replaced by `mock` and every cache moved to tmp_path."""
    real = translate.ask_cached

    def ask(prompt, role, schema, cache_dir, name):
        return real(prompt, role, schema, tmp_path / name, name)

    monkeypatch.setattr(translate, "chat", mock)
    for module in (translate, faithful, reconcile, review):
        monkeypatch.setattr(module, "ask_cached", ask)
    return check_pattern(text)


def entry(row, quote, verdict, code="same", explanation="x", fixed_text="", insert_after=-1, inserted_text="",
          inserted_code=""):
    return {"row": row, "quote": quote, "verdict": verdict, "code": code, "explanation": explanation,
            "fixed_text": fixed_text, "insert_after": insert_after, "inserted_text": inserted_text,
            "inserted_code": inserted_code}


# ---- A: the planted extra stitch ----
A_FIX = entry(3, "6 times, sc", "fix", explanation="a stray sc after the repeats",
              fixed_text="Round 3: *sc, 2 sc in next st; repeat from * 6 times (18)", code="6*[sc,sc2inc]")
A_ALICE = entry(3, "6 times, sc", "reading", code=A_READING, explanation="the last sc is the first sc of the repeats")


def test_case_a_a_reading_that_leaves_the_extra_stitch_out_is_refused_by_reconcile(monkeypatch, tmp_path):
    mock = Mock(A_LITERAL, A_READING)
    report = run(monkeypatch, tmp_path, A, mock)
    assert report.verdict.kind == "breaks" and report.verdict.row == 3
    assert user_message(report) == "❌ Breaks at Round 3: the pattern says 18, but the instructions make 19."
    assert report.rows[3].code == A_LITERAL and not report.rows[3].reading
    assert mock.calls("reconcile_row")  # it was asked for another reading ...
    assert any("it drops a stitch or chain" in p for p in mock.calls("reconcile_row"))  # ... and told why it was refused
    assert not any("translator read it another way" in p for p in mock.calls("faithful_row"))  # the checker never saw it


def test_case_a_alice_cannot_explain_it_away_and_bob_fixes_it(monkeypatch, tmp_path):
    mock = Mock(A_LITERAL, A_READING, alice=[[A_ALICE]], bob=[[A_FIX]])
    report = run(monkeypatch, tmp_path, A, mock)
    v = report.verdict
    assert v.kind == "breaks" and v.row == 3 and [f.row for f in v.fixes] == [3]
    assert user_message(report).startswith("❌ Breaks at Round 3: ")
    assert "change 'times, sc' to 'times'" in user_message(report)
    assert report.review.outcome == "fix" and not report.review.alice_passed and report.review.bob_passed
    assert not any("reviewer read this row" in p for p in mock.calls("faithful_row"))
    assert "6*[sc,sc2inc],sc" in report.code  # the report keeps the pattern as written




# ---- B: the planted missing round ----
B_ALICE = entry(3, "dc in next 2 sts", "reading", code=B_READING, explanation="2 sc in the same st")
B_INSERT = entry(2, "", "insert", explanation="a round seems to be missing after Round 2", insert_after=2,
                 inserted_text=B_MISSING, inserted_code=B_MISSING_CODE)


def test_case_b_a_reading_that_moves_the_stitches_is_refused_and_the_break_stands(monkeypatch, tmp_path):
    mock = Mock(B_LITERAL, B_READING, alice=[[B_ALICE]])  # Bob finds nothing to say
    report = run(monkeypatch, tmp_path, B, mock)
    assert report.verdict.kind == "breaks" and report.verdict.row == 3 and not report.verdict.fixes
    assert user_message(report).startswith("❌ Breaks at Round 3: ")
    assert report.rows[3].code == B_LITERAL and not report.rows[3].reading
    assert any("not allowed as a reading of the row: it moves the stitches" in p for p in mock.calls("review"))
    assert not any("reviewer read this row" in p for p in mock.calls("faithful_row"))  # refused before the checker


def test_case_b_alice_cannot_move_the_stitches_and_bob_inserts_the_missing_round(monkeypatch, tmp_path):
    mock = Mock(B_LITERAL, B_READING, alice=[[B_ALICE]], bob=[[B_INSERT]])
    report = run(monkeypatch, tmp_path, B, mock)
    v = report.verdict
    assert v.kind == "breaks" and v.row == 3 and [(f.row, f.insert) for f in v.fixes] == [(3, True)]
    assert user_message(report) == (
        "❌ Breaks at Round 3: a round seems to be missing before it. Suggested: insert "
        "'Round 3: (sc, 2 sc in next st) 12 times (36)' (re-checked: the pattern works with it).")
    assert report.review.outcome == "fix" and report.review.fixed_report.verdict.kind == "works"
    assert [r.code for r in report.review.fixed_report.rows if r.code][-2:] == [B_MISSING_CODE, B_LITERAL]
    assert report.review.fixed_report.stated == {1: 12, 2: 24, 3: 36, 4: 48}  # the pattern now has four rounds
    assert not any("reviewer read this row" in p for p in mock.calls("faithful_row"))
    assert fix_lines(report)[0].startswith("Suggested fix: insert a new round as Round 3")
    cleaned = clean_pattern(report)
    assert "this row was added" in cleaned and "Round 4:" in cleaned


# ---- C: a fix of a row that works under a counting reading is conditional ----
from frogless.engine import get_engine  # noqa: E402
from frogless.pipeline.report import PatternReport, RowResult  # noqa: E402
from frogless.pipeline.verdict import counting_fits, decide_verdict  # noqa: E402

CH = "Ch 12."
ROW1 = "Row 1: dc in 4th ch from hook and in each ch across (10)"  # 9 dc; 10 only if the chain counts
ROW2 = "Row 2: ch 3, dc in each st across (9)"
ROW3 = "Row 3: ch 3, dc in each st across (8)"  # 9 dc whatever the counting: a real mistake
CODES = ["12ch", "3sk,9dc,turn", "3ch,9dc,turn", "3ch,9dc"]


def report_of(texts):
    engine = get_engine()
    rows = [RowResult(index=i, source=t, code=CODES[i], origin="rules", faithful=True) for i, t in enumerate(texts)]
    text = "\n".join(texts)
    check = engine.check("\n".join(r.code for r in rows))
    verdict, stated, computed = decide_verdict(engine, text, rows, check)
    return engine, text, PatternReport(text=text, rows=rows, check=check, verdict=verdict, stated=stated,
                                       computed=computed)


def review_with(monkeypatch, tmp_path, engine, text, report, bob):
    mock = Mock("", "", alice=[[entry(1, "in each ch across", "reading", code="3sk,9dc,turn")]], bob=[bob])
    real = translate.ask_cached
    monkeypatch.setattr(translate, "chat", mock)
    for module in (faithful, review):
        monkeypatch.setattr(module, "ask_cached", lambda p, r, s, c, n: real(p, r, s, tmp_path / n, n))
    review.review_report(engine, text, report, cache_dir=tmp_path / "review", faithful_cache_dir=tmp_path / "f")
    return mock


FIX_ROW1 = entry(1, "(10)", "fix", explanation="9 dc, not 10", fixed_text="Row 1: dc in 4th ch from hook and in each ch across (9)")
FIX_ROW3 = entry(3, "(8)", "fix", explanation="9 dc, not 8", fixed_text="Row 3: ch 3, dc in each st across (9)")


def test_the_counting_reading_is_found_for_the_row_that_needs_it():
    engine, _, report = report_of([CH, ROW1, ROW2])
    assert report.verdict.kind == "ambiguous"  # the two ways of counting disagree about where it breaks
    fit = counting_fits(engine, report.rows, report.check)
    assert list(fit) == [1] and (fit[1].said, fit[1].made) == (10, 9)
    assert fit[1].readings == ["turning chain counted as a stitch"]


def test_case_c_a_fix_of_a_row_that_works_if_the_turning_chain_counts_is_conditional(monkeypatch, tmp_path):
    engine, text, report = report_of([CH, ROW1, ROW2])
    review_with(monkeypatch, tmp_path, engine, text, report, [FIX_ROW1])
    v = report.verdict
    assert v.kind == "ambiguous" and v.row == 1 and [f.conditional for f in v.fixes] == ["turning chain counted as a stitch"]
    assert user_message(report) == ("⚠ Row 1 works if the turning chain counts as a stitch; if not, it is one short "
                                    "(fix: change '(10)' to '(9)').")
    assert fix_lines(report)[0].startswith("Suggested fix, Row 1 (only if the turning chain does not count")
    assert "works if the turning chain counts as a stitch; if not, suggested fix" in clean_pattern(report)


def test_a_counting_reading_that_only_one_of_many_rows_needs_does_not_make_its_fix_conditional(monkeypatch, tmp_path):
    engine, text, report = report_of([CH, ROW1, ROW2, ROW3])  # one stated row in three fits only if the chain counts
    assert counting_fits(engine, report.rows, report.check) == {}
    review_with(monkeypatch, tmp_path, engine, text, report, [FIX_ROW1, FIX_ROW3])
    v = report.verdict
    assert v.kind == "breaks" and v.row == 1  # the default reading applies: the earliest row that misses its count
    assert not any(f.conditional for f in v.fixes)
    assert "turning chain" not in user_message(report)


def test_a_fix_of_a_row_that_fails_under_every_reading_is_not_conditional(monkeypatch, tmp_path):
    engine, text, report = report_of([CH, ROW1, ROW2, ROW3])
    review_with(monkeypatch, tmp_path, engine, text, report, [FIX_ROW1, FIX_ROW3])
    assert 3 not in counting_fits(engine, report.rows, report.check)


def test_the_pattern_saying_the_chain_counts_makes_the_reading_clear():
    engine, _, report = report_of([CH, ROW1.replace("across", "across, the ch 3 counts as a dc,"), ROW2, ROW3])
    assert 1 in counting_fits(engine, report.rows, report.check)
    engine, _, report = report_of([CH, ROW1.replace("across", "across, the ch 3 does not count as a st,"), ROW2, ROW3])
    assert counting_fits(engine, report.rows, report.check) == {}  # the pattern says it does not


def test_an_interpreted_verdict_is_refused_for_code_that_deletes_from_the_first_translation(monkeypatch, tmp_path):
    from frogless.pipeline.faithful import check_faithfulness
    from frogless.pipeline.translate import rule_rows, translate_flagged

    codes = [A_LITERAL, A_READING, A_READING]
    verdicts = ["mismatch", "interpreted", "interpreted"]  # the checker is fooled by the rewording twice

    def chat(role, messages, **opts):
        name = opts["prompt_cache_key"].split("-")[0]
        if name == "translate_row":
            body = {"code": codes.pop(0)}
        elif "English:\nRound 3:" in messages[0]["content"]:  # the row under test
            body = {"verdict": verdicts.pop(0), "reading": "the last sc is a restatement", "reason": "unclear"}
        else:
            body = {"verdict": "faithful", "reading": "", "reason": ""}
        return {"text": json.dumps(body), "usage": {"input_tokens": 1, "output_tokens": 1}, "cost_usd": 0.0}

    real = translate.ask_cached
    monkeypatch.setattr(translate, "chat", chat)
    monkeypatch.setattr(translate, "ask_cached", lambda p, r, s, c, n: real(p, r, s, tmp_path / n, n))
    monkeypatch.setattr(faithful, "ask_cached", translate.ask_cached)
    engine = get_engine()
    rows = translate_flagged(engine, A, rule_rows(engine, A), tmp_path / "t")[0]
    # the first translation is already in `rows`; the checker is not asked for a verdict on an unrelated rule row
    rows, _ = check_faithfulness(engine, A, rows, tmp_path / "f", tmp_path / "t")
    row = rows[3]
    assert row.status == "cannot" and row.code == "" and "drops a stitch or chain" in row.note
