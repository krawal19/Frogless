"""The stitch ledger: rows the engine cannot model are counted by the model and added up by our code.

chat() is mocked (no API calls); the cache goes to tmp_path.
"""

import json
from dataclasses import replace

from frogless.engine import CheckResult, RowInfo, get_engine
from frogless.pipeline import translate
from frogless.pipeline.ledger import Answer, count_ledger, judge, ledger_positions, read_answer
from frogless.pipeline.messages import user_message
from frogless.pipeline.output import clean_pattern
from frogless.pipeline.report import PatternReport, RowResult
from frogless.pipeline.translate import rule_rows
from frogless.pipeline.verdict import decide_verdict


class FakeEngine:
    """Code lines like "12dc" make one row of that many dc; "ring.R0" and "tie_up" make no row."""

    def notation_guide(self):
        return "GUIDE TEXT"

    def check(self, code):
        counts = [int(l[:-2]) for l in code.splitlines() if l.endswith("dc")]
        return CheckResult(ok=True, rows=[RowInfo(i + 1, n, {"dc": n}) for i, n in enumerate(counts)])


LEG = "Round 3: make the legs as described, sc around (18)"
TEXT = f"Round 1: 6 dc in ring (6)\nRound 2: 2 dc in each (12)\n{LEG}\nRound 4: dc in each dc around (18)"


def rows(leg=LEG, after="Round 4: dc in each dc around (18)", after_code="18dc"):
    return [
        RowResult(index=0, source="make a magic ring.", code="ring.R0", origin="rules", synthetic=True),
        RowResult(index=1, source="Round 1: 6 dc in ring (6)", code="6dc", origin="rules"),
        RowResult(index=2, source="Round 2: 2 dc in each (12)", code="12dc", origin="rules"),
        RowResult(index=3, source=leg, origin="model", status="cannot", note="legs worked back along a chain"),
        RowResult(index=4, source=after, code=after_code, origin="rules"),
    ]


def answer(uses=12, makes=18, skips=0, quotes=("make the legs as described",), explanation="6 legs x 3 dc = 18"):
    return {"uses": uses, "makes": makes, "skips": skips, "quotes": list(quotes), "explanation": explanation}


class FakeChat:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, role, messages, **opts):
        self.calls.append({"role": role, "prompt": messages[0]["content"], **opts})
        return {"text": json.dumps(self.replies.pop(0)), "usage": {"input_tokens": 100, "output_tokens": 5},
                "cost_usd": 0.01}


def run(monkeypatch, tmp_path, replies, rows_in=None, engine=None, text=TEXT):
    fake = FakeChat(replies)
    monkeypatch.setattr(translate, "chat", fake)
    engine = engine or FakeEngine()
    out, cost = count_ledger(engine, text, rows_in or rows(), tmp_path / "ledger")
    return fake, out, cost


def verdict(out, engine=None, text=TEXT):
    engine = engine or FakeEngine()
    code = "\n".join(r.code for r in out if r.code)
    v, stated, computed = decide_verdict(engine, text, out, engine.check(code))
    return v, PatternReport(text=text, rows=out, verdict=v, stated=stated, computed=computed)


# ---- which rows ----
def test_the_first_cannot_row_and_every_written_row_after_it_are_counted():
    assert ledger_positions(rows()) == [3, 4]
    assert ledger_positions(rows()[:3]) == []  # no cannot row, nothing to count


def test_synthetic_rows_are_not_counted():
    marker = RowResult(index=5, source="tie_up", code="tie_up", synthetic=True)
    assert ledger_positions(rows() + [marker]) == [3, 4]


# ---- rows that fit ----
def test_rows_that_fit_are_counted_only(monkeypatch, tmp_path):
    fake, out, cost = run(monkeypatch, tmp_path, [answer(), answer(uses=18, makes=18, quotes=["dc in each dc around"])])
    assert [c["role"] for c in fake.calls] == ["ledger", "ledger"] and cost == 0.02
    leg, after = out[3], out[4]
    assert (leg.ledger_uses, leg.ledger_makes, leg.ledger_ok) == (12, 18, True)
    assert leg.ledger_note == "6 legs x 3 dc = 18"
    assert (after.ledger_makes, after.ledger_ok, after.code) == (18, True, "")  # the engine never sees it
    v, rep = verdict(out)
    assert (v.kind, v.counted, v.row) == ("works_counts_only", [3, 4], None)
    assert rep.computed[3] == 18 and rep.computed[1] == 6
    assert user_message(rep) == ("✅ Stitch counts check out. Rounds 3, 4 were read by AI and checked by count only "
                                 "(they can't be modelled stitch by stitch).")


def test_the_prompt_holds_the_whole_pattern_after_the_static_instructions(monkeypatch, tmp_path):
    fake, _, _ = run(monkeypatch, tmp_path, [answer(), answer(uses=18, makes=18, quotes=["dc in each dc around"])])
    prompt = fake.calls[0]["prompt"]
    assert prompt.index("<pattern>") < prompt.index(TEXT) < prompt.index("The row: [3]")
    assert "Round 1: 6 dc in ring (6)" not in prompt.split("<pattern>")[0]
    assert fake.calls[0]["json_schema"]["required"] == ["uses", "makes", "skips", "quotes", "explanation"]
    assert fake.calls[0]["prompt_cache_key"] == fake.calls[1]["prompt_cache_key"]


def test_a_second_run_costs_nothing(monkeypatch, tmp_path):
    replies = [answer(), answer(uses=18, makes=18, quotes=["dc in each dc around"])]
    run(monkeypatch, tmp_path, replies)
    fake, out, cost = run(monkeypatch, tmp_path, [])
    assert fake.calls == [] and cost == 0.0 and out[3].ledger_ok and out[4].ledger_ok


def test_a_line_that_is_not_a_stitch_row_changes_nothing(monkeypatch, tmp_path):
    note = answer(uses=0, makes=0, quotes=[], explanation="stuffing, no stitches")
    mid = rows()
    mid.insert(4, RowResult(index=9, source="Stuff firmly.", origin="model", status="cannot"))
    fake, out, _ = run(monkeypatch, tmp_path, [answer(), note, answer(uses=18, makes=18, quotes=["dc in each dc around"])],
                       rows_in=mid)
    assert [r.ledger_ok for r in out[3:]] == [True, True, True]
    v, rep = verdict(out)
    assert v.kind == "works_counts_only" and v.counted == [3, 5]  # the stuffing line is not named


def test_a_range_of_rows_is_asked_once(monkeypatch, tmp_path):
    src = "Rounds 4-5: dc in each dc around (18)"
    rs = rows()
    rs.append(RowResult(index=5, source=src, code="18dc"))
    rs[4] = replace(rs[4], source=src)
    fake, out, _ = run(monkeypatch, tmp_path, [answer(), answer(uses=18, makes=18, quotes=["dc in each dc around"])], rows_in=rs)
    assert len(fake.calls) == 2 and [r.ledger_ok for r in out[3:]] == [True, True, True]


# ---- rows that do not fit ----
def test_a_count_that_misses_the_stated_total_is_a_break(monkeypatch, tmp_path):
    fake, out, _ = run(monkeypatch, tmp_path, [answer(makes=16, explanation="6 legs x 2 dc + 4 = 16")])
    assert len(fake.calls) == 1  # nothing after a break is asked
    assert (out[3].ledger_ok, out[4].ledger_ok) == (False, None)
    v, rep = verdict(out)
    assert (v.kind, v.row, v.ledger) == ("breaks", 3, True)
    assert user_message(rep) == "❌ Breaks at Round 3: the pattern says 18, but the instructions make 16 (counted by AI, not modelled)."


def test_stitches_worked_into_that_the_row_below_does_not_have_is_a_break(monkeypatch, tmp_path):
    _, out, _ = run(monkeypatch, tmp_path, [answer(uses=14)])
    assert out[3].ledger_ok is False
    v, rep = verdict(out)
    assert user_message(rep) == ("❌ Breaks at Round 3: the row works into 14 stitches of the row below, which has 12 "
                                 "(counted by AI, not modelled).")


def test_a_later_row_is_held_to_the_count_of_the_row_before_it(monkeypatch, tmp_path):
    _, out, _ = run(monkeypatch, tmp_path, [answer(), answer(uses=17, makes=18, quotes=["dc in each dc around"])])
    assert out[3].ledger_ok and out[4].ledger_ok is False
    assert verdict(out)[0].row == 4


def test_stitches_left_unworked_on_purpose_are_allowed(monkeypatch, tmp_path):
    leg = "Round 3: sc around, leave the last 2 stitches unworked (10)"
    _, out, _ = run(monkeypatch, tmp_path, [answer(uses=10, makes=10, quotes=["leave the last 2 stitches unworked"])],
                    rows_in=rows(leg=leg)[:4])
    assert out[3].ledger_ok is True
    _, out, _ = run(monkeypatch, tmp_path / "b", [answer(uses=10, makes=18)], rows_in=rows()[:4])
    assert out[3].ledger_ok is False  # the row does not say so


def test_joining_two_pieces_may_use_twice_the_row_below(monkeypatch, tmp_path):
    join = "Round 3: slip stitch through both pieces to join them together (12)"
    ok = answer(uses=24, makes=12, quotes=["join them together"], explanation="both pieces have 12 sts")
    _, out, _ = run(monkeypatch, tmp_path, [ok], rows_in=rows(leg=join)[:4])
    assert (out[3].ledger_uses, out[3].ledger_ok) == (24, True)
    assert verdict(out)[0].kind == "works_counts_only"
    # twice the row below is not allowed for a row that is not a join
    _, out, _ = run(monkeypatch, tmp_path / "b", [answer(uses=24, makes=18)], rows_in=rows()[:4])
    assert out[3].ledger_ok is False


# ---- answers that are rejected ----
def test_a_quote_that_is_not_in_the_row_rejects_the_answer(monkeypatch, tmp_path):
    fake, out, _ = run(monkeypatch, tmp_path, [answer(quotes=["worked back along a chain"])])
    assert len(fake.calls) == 1
    leg = out[3]
    assert leg.ledger_ok is None and leg.status == "cannot" and "rejected" in leg.ledger_note
    assert leg.note == "legs worked back along a chain"  # the reason it could not be modelled stays
    v, rep = verdict(out)
    assert (v.kind, v.row) == ("unreadable", 3)
    assert user_message(rep).startswith("❓ We couldn't read Round 3 (legs worked back along a chain).")


def test_quotes_ignore_case_and_spacing():
    a = read_answer(json.dumps(answer(quotes=["MAKE  the\nlegs"])), LEG)
    assert isinstance(a, Answer) and a.makes == 18


def test_bad_replies_are_rejected():
    for bad in ["not json", json.dumps({"uses": 1}), json.dumps(answer(uses=-1)), json.dumps(answer(uses=1.5)),
                json.dumps(answer(quotes=[])), json.dumps(answer(skips=20)), json.dumps(answer(quotes=[""]))]:
        assert isinstance(read_answer(bad, LEG), str), bad


def test_nothing_is_asked_when_the_pattern_breaks_before_the_first_row(monkeypatch, tmp_path):
    bad = rows()
    bad[2] = replace(bad[2], source="Round 2: 2 dc in each (13)")  # the code makes 12
    fake, out, cost = run(monkeypatch, tmp_path, [], rows_in=bad)
    assert fake.calls == [] and cost == 0.0 and all(r.ledger_ok is None for r in out)


# ---- the arithmetic on its own ----
def test_judge_takes_the_stated_total_and_the_row_below():
    a = Answer(12, 18, 0, ["x"], "")
    assert judge(LEG, a, [12]) == ("", [18])
    assert judge(LEG, a, None)[0] == ""  # no row below to compare with
    assert judge(LEG, Answer(12, 17, 0, ["x"], ""), [12])[0] == "the pattern says 18, but the instructions make 17"
    assert judge("Round 3: do the legs", Answer(12, 17, 0, ["x"], ""), [12])[0] == ""  # no stated total
    assert judge("Round 3: do the legs (3 sc)", Answer(12, 17, 0, ["x"], ""), [12])[0] == ""  # a typed count is no total


def test_a_fresh_start_works_into_nothing():
    a = Answer(0, 10, 0, ["x"], "")
    assert judge("Round 3: ch 10, sc across (10)", a, [12])[0] == ""
    assert judge("Round 3: sc around (10)", a, [12])[0] != ""


# ---- with the real engine: the rows before are checked by the engine, the rest by the ledger ----
OCTOPUS = """R1: 6 sc in magic ring (6)
R2: inc in each st around (12)
R3: sc in each st around (12)
R4: work the legs as described (18)
R5: sc in each st around (18)"""


def test_with_the_real_engine(monkeypatch, tmp_path):
    engine = get_engine()
    rs = [replace(r, status="cannot", note="legs") if r.source.startswith("r4") or r.source.startswith("rnd 4") else r
          for r in rule_rows(engine, OCTOPUS)]
    cannot = [r for r in rs if r.status != "ok"]
    assert len(cannot) == 1
    replies = [answer(uses=12, makes=18, quotes=["work the legs as described"]),
               answer(uses=18, makes=18, quotes=["sc in each st around"])]
    fake, out, _ = run(monkeypatch, tmp_path, replies, rows_in=rs, engine=engine, text=OCTOPUS)
    assert len(fake.calls) == 2
    v, rep = verdict(out, engine, OCTOPUS)
    assert v.kind == "works_counts_only" and v.counted == [4, 5]
    cleaned = clean_pattern(rep)
    assert "Round 4: work the legs as described (18) [counts checked; not modelled]" in cleaned
    assert "Round 5: sc in each st around (18) [counts checked; not modelled]" in cleaned
    assert "Round 3: sc in next 12 sts. (12)" in cleaned


def test_message_names_a_run_of_rounds_and_one_round():
    from frogless.pipeline.report import Verdict
    many = PatternReport(text="", rows=[RowResult(index=0, source="Round 1: sc", code="x")],
                         verdict=Verdict("works_counts_only", "", counted=[17, 18, 19]))
    assert user_message(many) == ("✅ Stitch counts check out. Rounds 17-19 were read by AI and checked by count only "
                                  "(they can't be modelled stitch by stitch).")
    one = PatternReport(text="", rows=many.rows, verdict=Verdict("works_counts_only", "", counted=[17], rows=[4]))
    assert user_message(one) == ("✅ Stitch counts check out. Round 17 was read by AI and checked by count only "
                                 "(they can't be modelled stitch by stitch). Round 4 was also read by AI and couldn't "
                                 "be double-checked.")
