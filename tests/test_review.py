"""Alice and Bob with a code referee (review.py).

chat() is mocked, no API calls; caches go to tmp_path. The fake engine reads "12dc" as one row of 12 dc.
"""

import json
from dataclasses import replace

import pytest

from frogless.engine import CheckError, CheckResult, RowInfo, get_engine
from frogless.pipeline import review, translate
from frogless.pipeline.check import check_pattern
from frogless.pipeline.messages import change_text, fix_lines, user_message
from frogless.pipeline.output import clean_pattern
from frogless.pipeline.report import PatternReport, RowResult
from frogless.pipeline.review import Entry, needs_review, review_report, vet
from frogless.pipeline.verdict import decide_verdict

R1 = "Round 1: 6 dc in ring (6)"
R2 = "Round 2: 2 dc in each (12)"
R3 = "Round 3: 2 dc in first, dc in each around (12)"
TEXT = "\n".join([R1, R2, R3])


class FakeEngine:
    def notation_guide(self):
        return "GUIDE TEXT"

    def check(self, code):
        rows = []
        for line in code.splitlines():
            if "BAD" in line:
                return CheckResult(ok=False, error=CheckError("unknown stitch", None, "invalid"))
            if line.endswith("dc"):
                rows.append(RowInfo(len(rows) + 1, int(line[:-2]), {"dc": int(line[:-2])}))
        return CheckResult(ok=True, rows=rows)

    def describe(self, code):
        return [f"Round {i + 1}: {line}" for i, line in enumerate(l for l in code.splitlines() if l.strip())]


def rows(r3_code="13dc", r3_status="ok", r3_source=R3):
    return [
        RowResult(index=0, source=R1, code="6dc", origin="rules"),
        RowResult(index=1, source=R2, code="12dc", origin="rules"),
        RowResult(index=2, source=r3_source, code=r3_code, origin="model", status=r3_status),
    ]


def report_for(rs, text=TEXT):
    engine = FakeEngine()
    check = engine.check("\n".join(r.code for r in rs if r.code))
    verdict, stated, computed = decide_verdict(engine, text, rs, check)
    return PatternReport(text=text, rows=rs, check=check, verdict=verdict, stated=stated, computed=computed)


def entry(row=2, quote="2 dc in first", verdict="ok", code="12dc", explanation="x", fixed_text=""):
    return {"row": row, "quote": quote, "verdict": verdict, "code": code, "explanation": explanation,
            "fixed_text": fixed_text}


FIX3 = entry(verdict="fix", explanation="the extra dc makes 13", fixed_text="Round 3: dc in each around (12)")


class Script:
    """A fake chat(). `alice`/`bob` are lists of replies (JSON objects) used in order; the last is repeated.
    The faithfulness checker says mismatch to a reading, interpreted to a fix and faithful to the rest,
    unless `judge` is given."""

    def __init__(self, alice=(), bob=(), judge=None):
        self.alice, self.bob, self.judge = list(alice), list(bob), judge
        self.prompts = {"alice": [], "bob": [], "judge": []}

    def __call__(self, role, messages, **opts):
        prompt = messages[0]["content"]
        if "Your side: ALICE" in prompt:
            who, queue = "alice", self.alice
        elif "Your side: BOB" in prompt:
            who, queue = "bob", self.bob
        else:
            who, queue = "judge", None
        self.prompts[who].append(prompt)
        if queue is not None:
            rows_ = queue.pop(0) if len(queue) > 1 else queue[0]
            body = {"summary": f"{who} says so", "rows": rows_}
        elif self.judge:
            body = self.judge(prompt)
        elif "reviewer read this row" in prompt:
            body = {"verdict": "mismatch", "reading": "", "reason": "it drops the extra dc the row names"}
        elif "edited by a reviewer" in prompt:
            body = {"verdict": "faithful", "reading": "", "reason": ""}
        else:
            body = {"verdict": "faithful", "reading": "", "reason": ""}
        return {"text": json.dumps(body), "usage": {"input_tokens": 100, "output_tokens": 5}, "cost_usd": 0.01}


def interpreted_judge(prompt):
    if "reviewer read this row" in prompt:
        return {"verdict": "interpreted", "reading": "the first dc counts in the 12", "reason": "unclear"}
    return {"verdict": "faithful", "reading": "", "reason": ""}


def run(monkeypatch, tmp_path, script, report=None):
    monkeypatch.setattr(translate, "chat", script)
    report = report or report_for(rows())
    cost = review_report(FakeEngine(), report.text, report, cache_dir=tmp_path / "review",
                         faithful_cache_dir=tmp_path / "faithful")
    return report, cost


# ---- when it runs ----
def test_it_runs_for_breaks_unreadable_and_ambiguous_only():
    assert needs_review(report_for(rows()))  # breaks
    assert needs_review(report_for(rows(r3_code="", r3_status="cannot")))  # unreadable
    assert not needs_review(report_for(rows(r3_code="12dc")))  # works
    ledger = report_for(rows())
    ledger.verdict = replace(ledger.verdict, ledger=True)
    assert not needs_review(ledger)


# ---- the referee's first look ----
def test_an_entry_whose_quote_is_not_in_the_row_is_discarded():
    good = Entry(2, "  2 DC in   first", "ok", "12dc", "")
    bad = Entry(2, "3 dc in first", "ok", "12dc", "")
    kept, reasons = vet("alice", rows(), [bad])
    assert kept == [] and "not in the row" in reasons[0]
    assert vet("alice", rows(), [good])[0] == [good]  # case and spacing do not matter


def test_unchanged_rows_synthetic_rows_and_wrong_verdicts_are_handled():
    rs = rows() + [RowResult(index=3, source="make a ring", code="ring.R0", synthetic=True)]
    kept, reasons = vet("alice", rs, [Entry(0, "", "ok", "same", ""), Entry(3, "ring", "ok", "6dc", ""),
                                      Entry(2, "dc", "fix", "12dc", "", "x")])
    assert kept == [] and len(reasons) == 2


def test_a_fix_must_change_the_text():
    same = Entry(2, "2 dc in first", "fix", "same", "", R3.upper())
    assert vet("bob", rows(), [same]) == ([], ["Row 2: a fix must give fixed_text that differs from the written row"])


# ---- the truth table ----
def test_alice_literal_means_it_works_and_bob_is_not_asked(monkeypatch, tmp_path):
    rep = report_for(rows(r3_code="", r3_status="cannot"))
    script = Script(alice=[[entry(quote="dc in each around", verdict="ok", code="12dc")]], bob=[[FIX3]])
    rep, cost = run(monkeypatch, tmp_path, script, rep)
    assert rep.verdict.kind == "works" and rep.verdict.interpreted == []
    assert rep.review.outcome == "works" and script.prompts["bob"] == []
    assert rep.rows[2].code == "12dc" and rep.rows[2].faithful is True
    assert user_message(rep) == "✅ This pattern works. Every row's stitch count checks out."
    assert cost == pytest.approx(0.02)  # Alice and the checker


def test_alice_with_a_reading_and_bob_passing_is_ambiguous(monkeypatch, tmp_path):
    script = Script(alice=[[entry(verdict="reading", explanation="the first dc counts in the 12")]], bob=[[FIX3]],
                    judge=interpreted_judge)
    rep, _ = run(monkeypatch, tmp_path, script)
    v = rep.verdict
    assert v.kind == "ambiguous" and v.row == 3 and [i.row for i in v.interpreted] == [3]
    assert [(f.row, f.fixed_text) for f in v.fixes] == [(3, "Round 3: dc in each around (12)")]
    assert rep.review.outcome == "ambiguous" and rep.review.alice_passed and rep.review.bob_passed
    assert user_message(rep) == (
        "⚠ Works if Round 3's '2 dc in first, dc in each around (12)' means the first dc counts in the 12 (unclear); "
        "read literally, Round 3 is wrong (fix: in Round 3, remove '2 dc in first,').")
    assert rep.rows[2].code == "12dc"  # the report shows Alice's reading


def test_alice_with_a_reading_and_bob_failing_works_with_interpretations(monkeypatch, tmp_path):
    bad_bob = [entry(verdict="fix", quote="no such words", fixed_text="Round 3: x (12)")]
    script = Script(alice=[[entry(verdict="reading", explanation="the first dc counts")]], bob=[bad_bob],
                    judge=interpreted_judge)
    rep, _ = run(monkeypatch, tmp_path, script)
    assert rep.verdict.kind == "works" and [i.row for i in rep.verdict.interpreted] == [3]
    assert rep.review.outcome == "works_with_readings" and not rep.review.bob_passed
    assert user_message(rep).startswith("✅ Works, if Round 3's '2 dc in first")
    assert len(script.prompts["alice"]) == 1  # no retry: one side passed


def test_alice_failing_and_bob_passing_breaks_with_the_fix(monkeypatch, tmp_path):
    script = Script(alice=[[entry(verdict="reading")]], bob=[[FIX3]])  # the checker calls Alice's reading a mismatch
    rep, _ = run(monkeypatch, tmp_path, script)
    v = rep.verdict
    assert v.kind == "breaks" and v.row == 3 and len(v.fixes) == 1
    assert rep.review.outcome == "fix" and rep.review.fixed_report.verdict.kind == "works"
    assert user_message(rep) == (
        "❌ Breaks at Round 3: the pattern says 12, but the instructions make 13. Suggested fix: in Round 3, "
        "remove '2 dc in first,' (re-checked: the pattern works with this fix).")
    assert fix_lines(rep) == [
        "Suggested fix, Round 3: remove '2 dc in first,' (the extra dc makes 13)",
        "  Round 3 would read: dc in each around (12)",
        "Re-checked: the pattern works with this fix."]
    assert rep.rows[2].code == "13dc"  # the report itself keeps the pattern as written


def test_a_planted_mistake_is_not_turned_into_works(monkeypatch, tmp_path):
    # Alice calls the silent fix the plain reading; the checker sees the dropped dc and says mismatch
    def judge(prompt):
        faithful = "edited by a reviewer" in prompt
        return {"verdict": "faithful" if faithful else "mismatch", "reading": "", "reason": "the row says 2 dc in first"}

    script = Script(alice=[[entry(verdict="ok", code="12dc")]], bob=[[FIX3]], judge=judge)
    rep, _ = run(monkeypatch, tmp_path, script)
    assert rep.review.alice_passed is False and rep.verdict.kind == "breaks" and rep.verdict.fixes


def test_both_failing_retries_with_the_referees_reasons_then_keeps_the_verdict(monkeypatch, tmp_path):
    bad_bob = [entry(verdict="fix", quote="no such words", fixed_text="Round 3: x (12)")]
    script = Script(alice=[[entry(verdict="reading")]], bob=[bad_bob])
    rep, _ = run(monkeypatch, tmp_path, script)
    assert len(script.prompts["alice"]) >= 2 and len(script.prompts["bob"]) >= 2  # an identical retry is cached
    assert "checked by a program and rejected" not in script.prompts["alice"][0]
    assert "the checker says your code does not match the written row" in script.prompts["alice"][1]
    assert "the quote 'no such words' is not in the row" in script.prompts["bob"][1]
    assert rep.verdict.kind == "breaks" and rep.verdict.fixes == [] and rep.review.outcome == "none"
    assert rep.review.attempts == 3 and rep.review.reasons
    assert user_message(rep) == "❌ Breaks at Round 3: the pattern says 12, but the instructions make 13."


def test_a_second_try_can_succeed(monkeypatch, tmp_path):
    bad_bob = [entry(verdict="fix", quote="no such words", fixed_text="Round 3: x (12)")]
    script = Script(alice=[[entry(verdict="reading")]], bob=[bad_bob, [FIX3]])
    rep, _ = run(monkeypatch, tmp_path, script)
    assert rep.review.attempts == 2 and rep.verdict.kind == "breaks" and len(rep.verdict.fixes) == 1


def test_engine_errors_and_count_misses_are_sent_back(monkeypatch, tmp_path):
    script = Script(alice=[[entry(verdict="ok", code="BAD")]], bob=[[entry(verdict="fix", code="13dc",
                                                                           fixed_text="Round 3: dc around (12)")]])
    run(monkeypatch, tmp_path, script)
    assert "the engine rejects the code" in script.prompts["alice"][1]
    assert "the engine check finds: Row 3: pattern says 12, the instructions make 13" in script.prompts["bob"][1]


def test_only_the_fixes_that_pass_are_shown_and_the_earliest_is_reported(monkeypatch, tmp_path):
    rs = rows()
    rs[1] = replace(rs[1], source="Round 2: 2 dc in first, 2 dc in each (12)", code="13dc")
    text = "\n".join([R1, rs[1].source, R3])
    fix2 = entry(row=1, quote="2 dc in first", verdict="fix", code="12dc", fixed_text="Round 2: 2 dc in each (12)")
    unneeded = entry(row=0, quote="6 dc", verdict="fix", code="same", fixed_text="Round 1: 6 dc in ring (6) now")
    script = Script(alice=[[entry(row=1, quote="2 dc in first", verdict="reading")]], bob=[[FIX3, unneeded, fix2]])
    rep, _ = run(monkeypatch, tmp_path, script, report_for(rs, text))
    v = rep.verdict
    assert v.kind == "breaks" and v.row == 2  # Round 2 is the earliest fixed row
    assert [f.row for f in v.fixes] == [2, 3]  # the unneeded fix of Round 1 was dropped
    assert "Round 1" not in " ".join(fix_lines(rep))
    assert user_message(rep).startswith("❌ Breaks at Round 2: ") and "fixes: in Round 2, remove" in user_message(rep)
    assert "these fixes" in user_message(rep)


def test_a_fix_that_does_not_make_the_pattern_work_is_not_shown(monkeypatch, tmp_path):
    wrong = entry(verdict="fix", code="14dc", fixed_text="Round 3: dc in each around (12)")
    script = Script(alice=[[entry(verdict="reading")]], bob=[[wrong]])
    rep, _ = run(monkeypatch, tmp_path, script)
    assert rep.verdict.fixes == [] and rep.review.outcome == "none"


def test_a_fix_is_judged_against_the_fixed_text_not_the_written_row(monkeypatch, tmp_path):
    script = Script(alice=[[entry(verdict="reading")]], bob=[[FIX3]])
    run(monkeypatch, tmp_path, script)
    fix_prompts = [p for p in script.prompts["judge"] if "edited by a reviewer" in p]
    assert len(fix_prompts) == 1
    tail = fix_prompts[0].split("The row as the designer wrote it:")[1]
    assert "Round 3: dc in each around (12)" in tail and "2 dc in first" not in tail


def test_the_prompt_puts_the_guide_first_and_the_pattern_last(monkeypatch, tmp_path):
    script = Script(alice=[[entry(verdict="reading")]], bob=[[FIX3]])
    run(monkeypatch, tmp_path, script)
    alice, bob = script.prompts["alice"][0], script.prompts["bob"][0]
    assert alice.index("GUIDE TEXT") < alice.index("<pattern>") < alice.index(TEXT) < alice.index("[2] " + R3)
    assert TEXT not in alice.split("<pattern>")[0]
    assert alice.split("Your side")[0] == bob.split("Your side")[0]  # the shared start can be cached


def test_a_second_run_costs_nothing(monkeypatch, tmp_path):
    script = Script(alice=[[entry(verdict="reading")]], bob=[[FIX3]])
    run(monkeypatch, tmp_path, script)
    again = Script()
    rep, cost = run(monkeypatch, tmp_path, again)
    assert cost == 0.0 and sum(map(len, again.prompts.values())) == 0 and rep.verdict.kind == "breaks"


def test_the_model_schema_asks_for_the_agreed_fields():
    item = review.ANSWER_SCHEMA["properties"]["rows"]["items"]
    assert item["required"] == ["row", "quote", "verdict", "code", "explanation", "fixed_text"]
    assert item["properties"]["verdict"]["enum"] == ["ok", "reading", "fix"]


# ---- the words ----
def test_change_text():
    assert change_text("Round 4: a b c d", "Round 4: a b d") == "remove 'c'"
    assert change_text("Round 4: dc (60)", "Round 4: dc (59)") == "change '(60)' to '(59)'"
    assert change_text("Round 4: a b c", "Round 4: a b c d") == "add 'd' after 'a b c'"
    assert change_text("Round 4: a b c d e", "Round 4: x b c d y") == "change 'a' to 'x', and change 'e' to 'y'"
    assert change_text("Round 4: a b c d e f g", "Round 4: x b y d z f w") == "make it read 'x b y d z f w'"


def test_check_pattern_wiring_without_a_model_never_reviews():
    rep = check_pattern("Round 1: 6 sc in ring (6)\nRound 2: inc in each st around (13)", use_model=False)
    assert rep.review is None


# ---- the real engine: the clean pattern marks the fix ----
def test_clean_pattern_marks_suggested_fixes(monkeypatch, tmp_path):
    engine = get_engine()
    src1, src2 = "Round 1: 6 sc in ring (6)", "Round 2: inc in each st around (13)"
    rs = [RowResult(index=0, source="make a magic ring.", code="ring.R0", synthetic=True),
          RowResult(index=1, source=src1, code="(6sc)@R0", origin="rules"),
          RowResult(index=2, source=src2, code="6sc2inc", origin="model")]
    text = f"{src1}\n{src2}"
    check = engine.check("\n".join(r.code for r in rs))
    verdict, stated, computed = decide_verdict(engine, text, rs, check)
    rep = PatternReport(text=text, rows=rs, check=check, verdict=verdict, stated=stated, computed=computed)
    assert verdict.kind == "breaks" and verdict.row == 2
    fix = {"row": 2, "quote": "(13)", "verdict": "fix", "code": "same", "explanation": "the total is wrong",
           "fixed_text": "Round 2: inc in each st around (12)"}
    script = Script(alice=[[{**fix, "verdict": "reading", "fixed_text": "", "code": "7sc2inc"}]], bob=[[fix]])
    monkeypatch.setattr(translate, "chat", script)
    review_report(engine, text, rep, cache_dir=tmp_path / "review", faithful_cache_dir=tmp_path / "faithful")
    assert rep.verdict.kind == "breaks" and rep.verdict.fixes[0].row == 2
    assert user_message(rep).endswith("Suggested fix: in Round 2, change '(13)' to '(12)' "
                                      "(re-checked: the pattern works with this fix).")
    cleaned = clean_pattern(rep)
    assert "[suggested fix: change '(13)' to '(12)']" in cleaned
    assert "Round 2: 2 sc in each of next 6 sts. (12)" in cleaned
    assert "6sc" not in cleaned and "@R0" not in cleaned


def test_a_gratuitous_change_the_checker_rejects_is_dropped_and_the_story_stands(monkeypatch, tmp_path):
    extra = entry(row=1, quote="2 dc in each", verdict="ok", code="012dc")  # same stitches, but the checker objects

    def judge(prompt):
        if "012dc" in prompt or "reviewer read this row" in prompt:
            return {"verdict": "mismatch", "reading": "", "reason": "it differs"}
        return {"verdict": "faithful", "reading": "", "reason": ""}

    script = Script(alice=[[entry(verdict="reading")]], bob=[[FIX3, extra]], judge=judge)
    rep, _ = run(monkeypatch, tmp_path, script)
    assert rep.verdict.kind == "breaks" and [f.row for f in rep.verdict.fixes] == [3]
    assert rep.review.fixed_report.rows[1].code == "12dc"  # the rejected change was not applied


def test_a_needed_change_the_checker_rejects_fails_the_story(monkeypatch, tmp_path):
    def judge(prompt):
        return {"verdict": "mismatch", "reading": "", "reason": "it differs"}

    script = Script(alice=[[entry(verdict="ok", code="12dc")]], bob=[[entry(verdict="ok", code="12dc")]], judge=judge)
    rep, _ = run(monkeypatch, tmp_path, script)
    assert rep.review.outcome == "none" and rep.verdict.kind == "breaks" and not rep.verdict.fixes


def test_new_code_for_a_row_already_confirmed_faithful_is_a_reading_not_the_plain_one(monkeypatch, tmp_path):
    rs = rows()
    rs[2] = replace(rs[2], faithful=True)  # the old code was already judged to be what the row says
    script = Script(alice=[[entry(verdict="ok", code="12dc")]], bob=[[FIX3]],
                    judge=lambda prompt: {"verdict": "faithful", "reading": "", "reason": ""})
    rep, _ = run(monkeypatch, tmp_path, script, report_for(rs))
    assert rep.review.outcome == "ambiguous" and len(script.prompts["bob"]) == 1  # Alice was not accepted as literal
    assert [i.row for i in rep.verdict.interpreted] == [3]
    assert rep.verdict.interpreted[0].reading == "12dc"  # what the code does, from the engine's English


# ---- Bob may insert a missing row ----
def insert_entry(after=1, text="Round 2b: 2 dc in each (12)", code="12dc", verdict="insert"):
    return {"row": after, "quote": "", "verdict": verdict, "code": "", "explanation": "a round seems to be missing",
            "fixed_text": "", "insert_after": after, "inserted_text": text, "inserted_code": code}


def test_bobs_schema_has_the_insert_fields_and_alices_is_unchanged():
    item = review.BOB_SCHEMA["properties"]["rows"]["items"]
    assert item["required"][-3:] == ["insert_after", "inserted_text", "inserted_code"]
    assert item["properties"]["verdict"]["enum"] == ["ok", "reading", "fix", "insert"]
    assert "insert_after" not in review.ANSWER_SCHEMA["properties"]["rows"]["items"]["properties"]
    assert review.SCHEMAS == {"alice": review.ANSWER_SCHEMA, "bob": review.BOB_SCHEMA}


def test_an_insert_is_read_and_vetted():
    got = review.read_reply(json.dumps({"summary": "s", "rows": [insert_entry(after=2)]}))
    entries = got[1]
    assert (entries[0].verdict, entries[0].row, entries[0].inserted_text) == ("insert", 2, "Round 2b: 2 dc in each (12)")
    assert vet("bob", rows(), entries) == (entries, [])
    kept, reasons = vet("alice", rows(), entries)  # Alice may not insert
    assert kept == [] and "not allowed for you" in reasons[0]
    bare = Entry(2, "", "insert", "", "x", "", "", "12dc")
    assert vet("bob", rows(), [bare])[0] == [] and "needs inserted_text" in vet("bob", rows(), [bare])[1][0]
    assert vet("bob", rows(), [Entry(9, "", "insert", "", "x", "", "Round 9", "12dc")])[1] == ["Row 9 is not a row of the pattern"]


def test_a_fix_of_an_existing_row_is_preferred_to_an_insert(monkeypatch, tmp_path):
    # both make the pattern work; fewer changes wins and a fix of what is written beats a new row
    script = Script(alice=[[entry(verdict="reading")]], bob=[[insert_entry(after=1), FIX3]])
    rep, _ = run(monkeypatch, tmp_path, script)
    v = rep.verdict
    assert v.kind == "breaks" and [(f.row, f.insert) for f in v.fixes] == [(3, False)]
    assert len(rep.review.fixed_report.rows) == 3  # the insert was pruned


def test_an_insert_shifts_the_rows_after_it():
    from frogless.pipeline.review import _assemble, _position

    new = Entry(1, "", "insert", "", "", "", "Round 2b: dc (12)", "12dc")
    fix = Entry(2, "dc", "fix", "same", "", "Round 3: dc in each around (12)")
    assembled = _assemble(rows(), [new, fix])
    assert [r.source for r in assembled] == [R1, R2, "Round 2b: dc (12)", "Round 3: dc in each around (12)"]
    assert [r.index for r in assembled] == [0, 1, 2, 3]
    assert (_position([new, fix], new), _position([new, fix], fix)) == (2, 3)


# ---- a row that is already right is not fixed ----
FIX_R2 = entry(1, "(12)", "fix", explanation="Round 3 needs 13 to work into",
               fixed_text="Round 2: 2 dc in each (13)", code="13dc")


def test_rows_that_make_their_stated_count_before_the_break_are_settled():
    assert review.settled_rows(FakeEngine(), TEXT, rows()) == {0, 1}  # Rounds 1-2 fit; Round 3 states 12, makes 13
    assert review.settled_rows(FakeEngine(), TEXT, rows(r3_code="12dc")) == set()  # nothing breaks: nothing to protect
    shaky = rows()
    shaky[1] = replace(shaky[1], faithful=False)  # a row whose translation is in doubt is not protected
    assert review.settled_rows(FakeEngine(), TEXT, shaky) == {0}


def test_a_fix_of_a_row_that_is_already_right_is_refused_and_points_to_insert():
    got = review.read_reply(json.dumps({"summary": "s", "rows": [FIX_R2]}))
    kept, reasons = vet("bob", rows(), got[1], {0, 1})
    assert kept == [] and "already makes its own stated count" in reasons[0] and "'insert'" in reasons[0]
    assert vet("bob", rows(), got[1])[0] == got[1]  # without the rule the fix would have been taken
    assert vet("bob", rows(), review.read_reply(json.dumps({"summary": "s", "rows": [FIX3]}))[1], {0, 1})[1] == []


def test_bob_changing_a_right_row_is_sent_back_and_with_no_insert_the_break_stays_where_it_was(monkeypatch, tmp_path):
    script = Script(alice=[[entry(verdict="reading")]], bob=[[FIX_R2]])
    rep, _ = run(monkeypatch, tmp_path, script)
    assert rep.review.outcome == "none" and rep.review.attempts == review.MAX_ATTEMPTS
    assert rep.verdict.kind == "breaks" and rep.verdict.row == 3 and not rep.verdict.fixes
    assert "already makes its own stated count" in script.prompts["bob"][1]  # Bob is told, and asked again


def test_an_insert_after_a_right_row_is_not_refused():
    entries = review.read_reply(json.dumps({"summary": "s", "rows": [insert_entry(after=1)]}))[1]
    assert vet("bob", rows(), entries, {0, 1}) == (entries, [])


# ---- fixes for the later rounds: Bob is asked again about the pattern as fixed so far ----
def _unconfirmed_second_row():
    rs = rows()
    rs[1] = replace(rs[1], origin="model")  # written by the model and never confirmed
    return report_for(rs)


FIX2 = entry(row=1, quote="2 dc in each", verdict="fix", code="12dc", fixed_text="Round 2: dc twice in each (12)")


def test_bob_is_asked_again_while_the_fixed_pattern_still_does_not_simply_work(monkeypatch, tmp_path):
    report = _unconfirmed_second_row()
    assert report.verdict.kind == "breaks"
    script = Script(alice=[[entry(verdict="reading")]], bob=[[FIX3], [FIX2]])
    rep, _ = run(monkeypatch, tmp_path, script, report)
    assert len(script.prompts["bob"]) == 2
    assert "already include the fixes made so far" in script.prompts["bob"][1]
    assert "Round 3: dc in each around (12)" in script.prompts["bob"][1]  # the second question is about the fixed pattern
    assert [f.row for f in rep.verdict.fixes] == [2, 3] and rep.verdict.row == 2
    assert rep.review.fixed_report.verdict.kind == "works"
    assert rep.review.fixed_report.rows[1].source == "Round 2: dc twice in each (12)"


def test_a_pattern_that_works_after_the_first_fix_is_not_asked_about_again(monkeypatch, tmp_path):
    script = Script(alice=[[entry(verdict="reading")]], bob=[[FIX3], [FIX2]])
    rep, _ = run(monkeypatch, tmp_path, script)
    assert len(script.prompts["bob"]) == 1 and [f.row for f in rep.verdict.fixes] == [3]


def test_a_later_fix_that_leaves_the_pattern_no_better_is_not_taken(monkeypatch, tmp_path):
    useless = entry(row=0, quote="6 dc", verdict="fix", code="same", fixed_text="Round 1: 6 dc in the ring (6)")
    script = Script(alice=[[entry(verdict="reading")]], bob=[[FIX3], [useless]])
    rep, _ = run(monkeypatch, tmp_path, script, _unconfirmed_second_row())
    assert [f.row for f in rep.verdict.fixes] == [3] and rep.verdict.kind == "breaks"
    assert len(script.prompts["bob"]) == 2  # asked once more, then stopped: nothing improved


def test_a_later_fix_on_a_row_already_fixed_goes_on_top_of_the_first():
    base = rows()
    first_fix = Entry(2, "2 dc in first", "fix", "12dc", "extra dc", "Round 3: dc in each around (12)")
    first = review.Story("bob", kept=[first_fix], fixes=[first_fix])
    first.rows = review._assemble(base, [first_fix])
    again = Entry(2, "dc in each", "fix", "12dc", "wording", "Round 3: dc around (12)")
    insert = Entry(0, "", "insert", "same", "missing", inserted_text="Round 1b: 6 dc (6)", inserted_code="6dc")
    more = review.Story("bob", kept=[again, insert], fixes=[again, insert])
    more.rows = review._assemble(first.rows, [again, insert])
    merged = review._merge(first, more, base)
    by_row = {e.row: e for e in merged.kept if e.verdict == "fix"}
    assert by_row[2].fixed_text == "Round 3: dc around (12)" and by_row[2].explanation == "extra dc"
    assert [e.row for e in merged.kept if e.verdict == "insert"] == [0]
    assert [r.source for r in review._assemble(base, merged.kept)] == [r.source for r in more.rows]
    clash = Entry(0, "", "insert", "same", "again", inserted_text="Round 1c: 6 dc (6)", inserted_code="6dc")
    again_more = review.Story("bob", kept=[clash], fixes=[clash])
    again_more.rows = review._assemble(more.rows, [clash])
    assert review._merge(merged, again_more, base) is None  # two inserts after the same row cannot be told apart
