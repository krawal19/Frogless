"""check_faithfulness(): one checker call per row, with chat() mocked (no API calls)."""

import json

from frogless.pipeline import faithful, translate
from frogless.pipeline.faithful import check_faithfulness
from frogless.pipeline.report import RowResult


class FakeEngine:
    def notation_guide(self):
        return "GUIDE TEXT"

    def describe(self, code):
        return [f"ENGLISH({line})" for line in code.splitlines() if line.strip()]


TEXT = "Round 1: 6 sc in ring (6)\nRound 2: weird thing\nRound 3: sc around"


def rows():
    return [
        RowResult(index=0, source="Round 1: 6 sc in ring (6)", code="(6sc)@R0", origin="rules"),
        RowResult(index=1, source="Round 2: weird thing", code="12sc", origin="model"),
        RowResult(index=2, source="Round 3: sc around", code="12sc", origin="rules"),
    ]


class FakeChat:
    """Stands in for chat(). Replies are returned in order; each is a dict (JSON-encoded here)."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, role, messages, **opts):
        self.calls.append({"role": role, "prompt": messages[0]["content"], **opts})
        return {"text": json.dumps(self.replies.pop(0)), "usage": {"input_tokens": 100, "output_tokens": 5},
                "cost_usd": 0.01}


def verdict(kind, reading="", reason=""):
    return {"verdict": kind, "reading": reading, "reason": reason}


def code(c):
    return {"code": c}


def run(monkeypatch, tmp_path, replies, rows_in=None, text=TEXT, engine=None):
    fake = FakeChat(replies)
    monkeypatch.setattr(translate, "chat", fake)
    out, cost = check_faithfulness(engine or FakeEngine(), text, rows_in or rows(), tmp_path / "f", tmp_path / "t")
    return fake, out, cost


def test_only_model_rows_and_countless_rule_rows_are_sent(monkeypatch, tmp_path):
    # row 0 (rules, states a count) is skipped; row 1 (model) and row 2 (rules, "sc around" states none) are sent
    fake, out, cost = run(monkeypatch, tmp_path, [verdict("faithful"), verdict("faithful")])
    assert [c["role"] for c in fake.calls] == ["faithfulness", "faithfulness"]
    assert fake.calls[0]["json_schema"] == faithful.ANSWER_SCHEMA
    row_part = fake.calls[0]["prompt"].split("</pattern>")[1]
    assert "Round 2: weird thing" in row_part and "ENGLISH(12sc)" in row_part
    assert "Round 1: 6 sc in ring" not in row_part
    assert [r.faithful for r in out] == [None, True, True]
    assert out[0].english == ""  # the stated-count gate vouches for it
    assert out[1].english == "ENGLISH(12sc)" and out[2].english == "ENGLISH(12sc)"  # only its own sentence
    assert cost == 0.02


def test_synthetic_and_codeless_rows_are_skipped(monkeypatch, tmp_path):
    rs = rows()
    rs[1] = RowResult(index=1, source="make a magic ring.", code="ring.R0", origin="model", synthetic=True)
    rs[2] = RowResult(index=2, source="fasten off", code="", origin="model")
    fake, out, cost = run(monkeypatch, tmp_path, [], rs)
    assert fake.calls == [] and cost == 0


def test_interpreted_counts_as_faithful_and_keeps_the_reading(monkeypatch, tmp_path):
    _, out, _ = run(monkeypatch, tmp_path, [verdict("interpreted", "1 dc in each of the 3 dc", "3dc cannot fit"),
                                           verdict("faithful")])
    assert out[1].faithful is True
    assert (out[1].reading, out[1].why) == ("1 dc in each of the 3 dc", "3dc cannot fit")
    assert out[1].note == "read as 1 dc in each of the 3 dc (3dc cannot fit)"


def test_mismatch_retranslates_with_feedback_then_passes(monkeypatch, tmp_path):
    replies = [verdict("mismatch", reason="makes 12 sc but the row says 13"), code("13sc"), verdict("faithful"),
               verdict("faithful")]
    fake, out, cost = run(monkeypatch, tmp_path, replies)
    translate_call = fake.calls[1]
    assert translate_call["role"] == "translator"
    assert "previous attempt for this row was wrong, because: makes 12 sc but the row says 13" in translate_call["prompt"]
    assert "ENGLISH(12sc)" in translate_call["prompt"]  # what the old code said
    assert (out[1].code, out[1].faithful, out[1].origin) == ("13sc", True, "model")
    assert out[1].english == "ENGLISH(13sc)"
    assert len(fake.calls) == 4 and cost == 0.04


def test_three_translations_that_mismatch_make_the_row_unreadable(monkeypatch, tmp_path):
    replies = [verdict("mismatch", reason="first"), code("11sc"), verdict("mismatch", reason="second"),
               code("10sc"), verdict("mismatch", reason="third"), verdict("faithful")]
    fake, out, _ = run(monkeypatch, tmp_path, replies)
    assert sum(c["role"] == "translator" for c in fake.calls) == 2  # translations 2 and 3
    assert (out[1].status, out[1].code, out[1].faithful) == ("cannot", "", False)
    assert out[1].note == "couldn't read this row reliably: third"
    assert out[2].faithful is True  # the other rows are still checked


def test_mismatching_rule_row_goes_to_the_model_once_then_follows_the_loop(monkeypatch, tmp_path):
    rs = rows()
    rs[1] = RowResult(index=1, source="Round 2: inc in each st", code="12sc", origin="rules")
    replies = [verdict("mismatch", reason="makes sc, not inc"), code("6*[sc2inc]"), verdict("faithful"),
               verdict("faithful")]
    fake, out, _ = run(monkeypatch, tmp_path, replies, rs)
    assert (out[1].origin, out[1].code, out[1].faithful) == ("model", "6*[sc2inc]", True)
    assert [c["role"] for c in fake.calls] == ["faithfulness", "translator", "faithfulness", "faithfulness"]


def test_silent_fix_is_a_mismatch_and_ends_as_unreadable(monkeypatch, tmp_path):
    text = "Round 1: 6 sc in ring (6)\nRound 2: 13 sc (13)"
    rs = [RowResult(index=0, source="Round 1: 6 sc in ring (6)", code="(6sc)@R0"),
          RowResult(index=1, source="Round 2: 13 sc (13)", code="12sc", origin="model")]
    reason = "the row says 13 sc but the code makes 12"
    replies = [verdict("mismatch", reason=reason), code("12sc"), verdict("mismatch", reason=reason),
               code("12sc"), verdict("mismatch", reason=reason)]
    _, out, _ = run(monkeypatch, tmp_path, replies, rs, text)
    assert out[1].status == "cannot" and "13 sc but the code makes 12" in out[1].note


def test_cannot_tell_leaves_faithful_unknown(monkeypatch, tmp_path):
    _, out, _ = run(monkeypatch, tmp_path, [verdict("cannot_tell", reason="UNSUPPORTED part"), verdict("faithful")])
    assert out[1].faithful is None and out[1].note == "UNSUPPORTED part"


def test_partly_unsupported_english_is_flagged_to_the_model(monkeypatch, tmp_path):
    class Partly(FakeEngine):
        def describe(self, code):
            return ["fine", "UNSUPPORTED: " + code]

    fake, _, _ = run(monkeypatch, tmp_path, [verdict("cannot_tell"), verdict("cannot_tell")], engine=Partly())
    assert 'start with "UNSUPPORTED"' in fake.calls[0]["prompt"]


def test_wholly_unsupported_english_is_not_sent(monkeypatch, tmp_path):
    class Nothing(FakeEngine):
        def describe(self, code):
            return ["UNSUPPORTED: " + code]

    fake, out, cost = run(monkeypatch, tmp_path, [], engine=Nothing())
    assert fake.calls == [] and cost == 0
    assert out[1].faithful is None and "couldn't be compared" in out[1].note


def test_replies_are_cached_on_disk(monkeypatch, tmp_path):
    run(monkeypatch, tmp_path, [verdict("faithful"), verdict("faithful")])
    fake, out, cost = run(monkeypatch, tmp_path, [])
    assert fake.calls == [] and cost == 0 and out[1].faithful is True


def test_an_invalid_reply_means_cannot_tell(monkeypatch, tmp_path):
    _, out, _ = run(monkeypatch, tmp_path, [{"verdict": "banana"}, verdict("faithful")])
    assert out[1].faithful is None
