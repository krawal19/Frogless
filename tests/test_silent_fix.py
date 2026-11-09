"""Silent fixes: a count that fits only because the code changed the stitches must never pass as "works".

Pattern C (examples/demo): "hdc in 3rd ch from hook ... (12)" on Ch 13 skips 2 chains and makes 11 hdc. A model that
writes `sk,12hdc` (skip 1) makes the stated 12 fit by working one more stitch. The right answer is 11 hdc, which fits
the 12 only if the turning chain counts, and the verdict says exactly that. Real engine, every model reply mocked.
"""

import json
from dataclasses import replace
from pathlib import Path

from frogless.engine import get_engine
from frogless.patterns.placement import chain_from_hook
from frogless.pipeline import faithful, reconcile, review, translate
from frogless.pipeline.check import check_pattern
from frogless.pipeline.faithful import check_faithfulness
from frogless.pipeline.gate import gate_translation
from frogless.pipeline.guards import hook_problem
from frogless.pipeline.report import RowResult
from frogless.pipeline.translate import rule_rows
from frogless.pipeline.verdict import TURN_COUNTS

PATTERN_C = (Path(__file__).parent.parent / "examples" / "demo" / "Pattern C.txt").read_text(encoding="utf-8")
ENGINE = get_engine()
LITERAL = "2sk,11hdc,2ch,turn"  # skip 2, 11 hdc
FIT_ONLY = "sk,12hdc,2ch,turn"  # skip 1, 12 hdc: fits the 12 by working one more stitch
LATER = "11hdc,2ch,turn"
LAST = "11hdc"


def run(monkeypatch, tmp_path, text, first_row, rest=None, judge=None):
    """check_pattern() with every model reply mocked: `first_row` is the list of the three attempts at the first row
    the model is asked about, `rest` {row number: code} the answer for every other row. Returns (report, prompts)."""
    seen = []

    def chat(role, messages, **opts):
        prompt, name = messages[0]["content"], opts.get("prompt_cache_key", "").split("-")[0]
        seen.append((name, prompt))
        if name == "translate_row":
            n = int(prompt.split("Translate row ")[1].split(" now")[0])
            attempt = int(prompt.split("Attempt ")[1].split(" of")[0]) if "Attempt " in prompt.split("Translate row")[-1] else 1
            if n == first_row[0]:
                code = first_row[1][min(attempt, len(first_row[1])) - 1]
            else:
                code = (rest or {}).get(n, LATER)
            body = {"code": code}
        elif name == "faithful_row":
            body = (judge or (lambda p: {"verdict": "faithful", "reading": "", "reason": ""}))(prompt)
        else:
            body = {"summary": "x", "rows": []}
        return {"text": json.dumps(body), "usage": {"input_tokens": 1, "output_tokens": 1}, "cost_usd": 0.0}

    real = translate.ask_cached
    monkeypatch.setattr(translate, "chat", chat)
    for module in (translate, faithful, reconcile, review):
        monkeypatch.setattr(module, "ask_cached", lambda p, r, s, c, n: real(p, r, s, tmp_path / n, n))
    return check_pattern(text, terms="US", review=False), seen


def later_rows(last):
    return {n: LATER for n in range(2, last)} | {last: LAST}


# ---- Pattern C: the model's count-fitting sample must not win ----
def test_pattern_c_a_sample_that_skips_a_chain_too_few_does_not_win(monkeypatch, tmp_path):
    report, _ = run(monkeypatch, tmp_path, PATTERN_C, (1, [FIT_ONLY, LITERAL, LITERAL]), later_rows(8))
    assert report.rows[1].code == LITERAL  # 11 hdc, not the 12 that only fits by skipping one chain less
    assert "started in the wrong chain" in report.rows[1].note or "attempts agree" in report.rows[1].note
    assert report.verdict.kind == "works" and report.verdict.reading == TURN_COUNTS
    assert "turning chain counts" in report.verdict.message


def test_pattern_c_the_count_fitting_sample_alone_is_never_a_plain_works(monkeypatch, tmp_path):
    # all three attempts (and the retries) skip one chain: the 12 fits, the words do not
    report, seen = run(monkeypatch, tmp_path, PATTERN_C, (1, [FIT_ONLY]), later_rows(8))
    assert report.verdict.kind == "unreadable" and report.verdict.row == 1
    assert report.rows[1].code == "" and "start in chain 3" in report.rows[1].note
    retries = [p for n, p in seen if n == "translate_row" and "previous attempt" in p]
    assert retries and "starts in chain 2" in retries[0]  # the model was told why


def test_pattern_c_the_judge_saying_faithful_does_not_let_the_wrong_start_through(monkeypatch, tmp_path):
    report, _ = run(monkeypatch, tmp_path, PATTERN_C, (1, [FIT_ONLY]), later_rows(8),
                    judge=lambda p: {"verdict": "faithful", "reading": "", "reason": ""})
    assert not (report.verdict.kind == "works" and not report.verdict.reading)


def test_describe_tells_one_chain_skipped_from_two():
    said = lambda code: ENGINE.describe("13ch\n" + code)[1]  # noqa: E731
    assert said("2sk,11hdc,turn") == "Row 1: hdc in 3rd ch from hook and in each ch across, turn."
    assert said("sk,12hdc,turn") != said("2sk,11hdc,turn")
    assert said("sk,12hdc,turn") == "Row 1: skip next ch, hdc in next 12 ch, turn."


# ---- the rules translator's literal code is kept on a gated line and wins when it fits the turning chain ----
LITERAL_TEXT = "Ch 13.\nRow 1: hdc in 3rd ch from hook and in each ch across, turn (12)\nRow 2: ch 2, hdc in each st across (12)"


def test_the_gate_keeps_the_rules_code_as_the_literal_reading():
    rows = rule_rows(ENGINE, LITERAL_TEXT)
    assert [(r.status, r.code, r.literal) for r in rows[1:]] == [
        ("flagged", "", "11hdc,turn"), ("flagged", "", "2ch,11hdc")]
    assert rows[1].note == "stated count 12, translation makes 11"


def test_a_literal_that_fits_only_if_the_turning_chain_counts_beats_a_count_fitting_sample(monkeypatch, tmp_path):
    report, _ = run(monkeypatch, tmp_path, LITERAL_TEXT, (1, ["sk,12hdc,turn"]), {2: "2ch,11hdc"})
    assert report.rows[1].code == "11hdc,turn" and report.rows[1].origin == "rules"
    assert report.verdict.kind == "works" and report.verdict.reading == TURN_COUNTS


def test_a_literal_that_misses_the_count_both_ways_does_not_stop_a_count_fitting_sample(monkeypatch, tmp_path):
    # the rules made 6 where the row says 12: that is a misreading (no turning chain explains it), the model's 12 wins
    text = "Round 1: 6 sc in a magic ring (6)\nRound 2: 2 sc in each st around (12)"
    rows = rule_rows(ENGINE, text)
    rows[2] = replace(rows[2], status="flagged", code="", literal="6sc")
    monkeypatch.setattr(translate, "chat", lambda role, messages, **o: {
        "text": json.dumps({"code": "6*[sc2inc]"}), "usage": {"input_tokens": 1, "output_tokens": 1}, "cost_usd": 0.0})
    out, _ = translate.translate_flagged(ENGINE, text, rows, cache_dir=tmp_path, samples=3, judge_cache_dir=tmp_path)
    assert out[2].code == "6*[sc2inc]" and out[2].origin == "model"


def test_lines_with_the_same_words_as_a_flagged_row_are_flagged_too():
    # "Rows 2-8" is one line per row: the rows after the flagged one only fitted a hole
    lines = gate_translation(ENGINE, ENGINE.translate(PATTERN_C), PATTERN_C).lines
    assert [l.parsed for l in lines] == [True] + [False] * 8
    assert lines[3].reason == "same words as a row that could not be read" and lines[3].literal == ""


# ---- the guards use the literal ----
def test_an_interpreted_verdict_is_measured_against_the_literal_not_the_models_code(monkeypatch, tmp_path):
    from tests.test_readings_end_to_end import A, A_LITERAL, A_READING

    rows = rule_rows(ENGINE, A)
    rows[3] = replace(rows[3], code=A_READING, origin="model", status="ok", literal=A_LITERAL)  # the gate had kept the literal
    monkeypatch.setattr(faithful, "_judge", lambda *a, **k: (
        {"verdict": "interpreted", "reading": "the last sc is a restatement", "reason": "unclear"}, 0.0))
    monkeypatch.setattr(faithful, "retranslate_row", lambda *a, **k: (replace(rows[3]), 0.0))
    out, _ = check_faithfulness(ENGINE, A, rows, tmp_path / "f", tmp_path / "t")
    assert out[3].status == "cannot" and "drops a stitch or chain" in out[3].note


# ---- the Nth-chain-from-hook guard ----
def test_the_chain_a_row_names_from_the_hook():
    assert chain_from_hook("Row 1: hdc in 3rd ch from hook and in each ch across, ch 2, turn (12)") == 3
    assert chain_from_hook("dc in the 4th chain from the hook") == 4
    assert chain_from_hook("Row 1: sc in each st across") is None


def test_code_that_starts_in_another_chain_than_the_row_names_is_a_problem():
    row, lines = "Row 1: hdc in 3rd ch from hook and in each ch across (12)", ["Row 1: hdc in 3rd ch from hook (12)"]
    assert hook_problem(ENGINE, "13ch", "2sk,11hdc,turn", row, lines) == ""
    assert "starts in chain 2" in hook_problem(ENGINE, "13ch", "sk,12hdc,turn", row, lines)
    assert hook_problem(ENGINE, "13ch", "11hdc,turn", row, lines) == ""  # the engine's plain "next 11 ch"
    assert hook_problem(ENGINE, "13ch", "sk,12hdc", "Row 1: hdc in each ch across", lines) == ""  # names no chain
    # the pattern itself saying the turning chain counts allows one skip fewer
    counts = ["Row 1: hdc in 3rd ch from hook (12)", "Row 2: ch 2 (counts as first hdc), hdc in each st across"]
    assert hook_problem(ENGINE, "13ch", "sk,12hdc,turn", row, counts) == ""
