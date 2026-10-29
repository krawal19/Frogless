"""user_message(): the wording for each verdict kind."""

from frogless.pipeline.check import check_pattern
from frogless.pipeline.messages import user_message
from frogless.pipeline.report import Alternative, Interpreted, PatternReport, RowResult, Verdict
from frogless.pipeline.verdict import PLAIN, TURN_COUNTS


def report(verdict, word="Round", n=3, stated=None, computed=None, rows=None):
    rows = rows or [RowResult(index=i, source=f"{word} {i + 1}: sc around", code="x") for i in range(n)]
    return PatternReport(text="", rows=rows, verdict=verdict, stated=stated or {}, computed=computed or {})


def test_works():
    msg = user_message(report(Verdict("works", "ok")))
    assert msg == "✅ This pattern works. Every row's stitch count checks out."


def test_works_with_interpretations_one_clause_per_row():
    v = Verdict("works", "ok", interpreted=[
        Interpreted(2, "Round 2: 3dc in each dc on the side (3)", "1 dc in each of the 3 dc", "3 dc per dc cannot make 3"),
        Interpreted(5, "Round 5: sc in the gap (12)", "sc in each of the 12 sts", "no gap is marked")])
    assert user_message(report(v, n=5)) == (
        "✅ Works, if Round 2's '3dc in each dc on the side (3)' means 1 dc in each of the 3 dc "
        "(3 dc per dc cannot make 3), and if Round 5's 'sc in the gap (12)' means sc in each of the 12 sts "
        "(no gap is marked).")


def test_interpreted_range_shares_a_clause_and_row_is_used_when_the_pattern_says_row():
    src = "Rows 2-4: sc across"
    v = Verdict("works", "ok", interpreted=[Interpreted(n, src, "sc in each st", "unclear") for n in (2, 3, 4)])
    rows = [RowResult(index=i, source=src, code="x") for i in range(3)]
    assert user_message(report(v, word="Row", rows=rows)) == "✅ Works, if 'sc across' in Rows 2-4 means sc in each st (unclear)."


def test_ambiguous_turning_chain():
    alts = [Alternative(PLAIN, 4, 13, 12), Alternative(TURN_COUNTS, None)]
    msg = user_message(report(Verdict("ambiguous", "x", row=4, alternatives=alts), word="Row"))
    assert msg == ("⚠ Depends on how you count turning chains. If the turning chain counts as a stitch: works. "
                   "If not: Row 4 is one stitch short.")


def test_ambiguous_extra_stitches():
    alts = [Alternative(PLAIN, None), Alternative(TURN_COUNTS, 4, 12, 15)]
    msg = user_message(report(Verdict("ambiguous", "x", row=4, alternatives=alts)))
    assert msg.endswith("If the turning chain counts as a stitch: Round 4 is 3 stitches over. If not: works.")


def test_breaks_with_counts():
    v = Verdict("breaks", "Round 5: pattern says 24, the instructions make 25", row=5)
    assert user_message(report(v, stated={5: 24}, computed={5: 25})) == (
        "❌ Breaks at Round 5: the pattern says 24, but the instructions make 25.")


def test_breaks_uses_row_when_the_pattern_does():
    v = Verdict("breaks", "x", row=2)
    assert user_message(report(v, word="Row", stated={2: 10}, computed={2: 9})).startswith("❌ Breaks at Row 2:")


def test_breaks_without_a_stated_count_gives_the_reason():
    v = Verdict("breaks", "Round 3: Round 3 has 7 stitches but the row before only has 6", row=3)
    assert user_message(report(v)) == "❌ Breaks at Round 3: Round 3 has 7 stitches but the row before only has 6."


def test_unreadable_says_everything_before_checks_out_only_when_true():
    rows = [RowResult(index=0, source="Round 1: 6 sc in ring (6)", code="x"),
            RowResult(index=1, source="Round 2: gibberish", code="", status="cannot",
                      note="couldn't read this row reliably: wrong count")]
    v = Verdict("unreadable", "x", row=2)
    msg = user_message(report(v, rows=rows, computed={1: 6}))
    assert msg == ("❓ We couldn't read Round 2 (couldn't read this row reliably: wrong count). "
                   "Everything before it checks out.")
    assert "Everything before" not in user_message(report(v, rows=rows, computed={}))  # nothing before it
    v.rows = [1]  # a row before it was never confirmed
    assert "Everything before" not in user_message(report(v, rows=rows, computed={1: 6}))


def test_works_unverified():
    v = Verdict("works_unverified", "x", rows=[3, 5])
    assert user_message(report(v, n=5)) == (
        "✅ Stitch counts check out, but Rounds 3, 5 couldn't be double-checked.")
    assert "Round 3 couldn't be double-checked" in user_message(report(Verdict("works_unverified", "x", rows=[3])))


def test_real_pattern_end_to_end_without_a_model():
    ok = check_pattern("Round 1: 6 sc in ring (6)\nRound 2: inc in each st around (12)", use_model=False)
    assert user_message(ok) == "✅ This pattern works. Every row's stitch count checks out."
    bad = check_pattern("Round 1: 6 sc in ring (6)\nRound 2: inc in each st around (13)", use_model=False)
    # without a model the row stays flagged by the stated-count gate, so it cannot be judged
    assert user_message(bad).startswith("❓ We couldn't read Round 2 (")
    assert user_message(bad).endswith("Everything before it checks out.")


def test_turning_chain_fallback_is_flagged_not_a_silent_pass():
    msg = user_message(report(Verdict("works", "ok", reading=TURN_COUNTS)))
    assert msg == "⚠ Works only if the turning chain counts as a stitch."
    msg = user_message(report(Verdict("works_unverified", "x", rows=[3], reading=TURN_COUNTS), n=5))
    assert msg.startswith("✅ Stitch counts check out, but Round 3 couldn't be double-checked")
    assert msg.endswith("⚠ Works only if the turning chain counts as a stitch.")


def test_chains_left_out_fallback_is_flagged():
    assert user_message(report(Verdict("works", "ok", chains_left_out=True))) == (
        "⚠ The counts only work if the chains are left out.")
    both = Verdict("works", "ok", reading=TURN_COUNTS, chains_left_out=True)
    assert user_message(report(both)) == ("⚠ Works only if the turning chain counts as a stitch. "
                                          "The counts only work if the chains are left out.")
    interp = Verdict("works", "ok", chains_left_out=True,
                     interpreted=[Interpreted(2, "Round 2: sc in the gap (12)", "sc in each of the 12 sts", "no gap")])
    assert user_message(report(interp)).endswith("⚠ The counts only work if the chains are left out.")
