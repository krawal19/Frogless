"""translate_flagged(): one model call per flagged row, with chat() mocked (no API calls)."""

import json

from frogless.pipeline import translate
from frogless.pipeline.report import RowResult
from frogless.pipeline.translate import translate_flagged

TEXT = "Round 1: 6 sc in ring\nRound 2: weird thing one\nRound 3: weird thing two"


class FakeEngine:
    def notation_guide(self):
        return "GUIDE TEXT"


def make_rows():
    return [
        RowResult(index=0, source="Round 1: 6 sc in ring", code="6sc", origin="rules", status="ok"),
        RowResult(index=1, source="Round 2: weird thing one", origin="none", status="flagged", note="unreadable"),
        RowResult(index=2, source="Round 3: weird thing two", origin="none", status="flagged", note="unreadable"),
    ]


class FakeChat:
    """Stands in for chat(); `replies` are returned in order as the JSON reply text."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, role, messages, **opts):
        self.calls.append({"role": role, "prompt": messages[0]["content"], **opts})
        text = self.replies.pop(0)
        return {"text": text, "usage": {"input_tokens": 100, "output_tokens": 5}, "cost_usd": 0.01}


def answer(code):
    return json.dumps({"code": code})


def run(monkeypatch, tmp_path, replies, rows=None):
    fake = FakeChat(replies)
    monkeypatch.setattr(translate, "chat", fake)
    out, cost = translate_flagged(FakeEngine(), TEXT, rows or make_rows(), cache_dir=tmp_path)
    return fake, out, cost


def test_rows_in_order_with_earlier_answers_as_context(monkeypatch, tmp_path):
    fake, rows, cost = run(monkeypatch, tmp_path, [answer("12sc"), answer("18sc")])
    assert len(fake.calls) == 2
    assert "Translate row 1 now" in fake.calls[0]["prompt"]
    assert "Translate row 2 now" in fake.calls[1]["prompt"]
    assert "[2] Round 3: weird thing two\n    => ?" in fake.calls[0]["prompt"]  # not translated yet
    assert "[1] Round 2: weird thing one\n    => 12sc" in fake.calls[1]["prompt"]  # earlier answer
    assert "GUIDE TEXT" in fake.calls[0]["prompt"]
    assert fake.calls[0]["json_schema"] == translate.ANSWER_SCHEMA
    assert [(r.code, r.origin, r.status) for r in rows] == [
        ("6sc", "rules", "ok"), ("12sc", "model", "ok"), ("18sc", "model", "ok")]
    assert cost == 0.02


def test_static_prefix_is_the_same_for_every_row(monkeypatch, tmp_path):
    fake, *_ = run(monkeypatch, tmp_path, [answer("12sc"), answer("18sc")])
    prefix = [c["prompt"].split("<pattern>")[0] for c in fake.calls]
    assert prefix[0] == prefix[1]
    assert fake.calls[0]["prompt_cache_key"] == fake.calls[1]["prompt_cache_key"]


def test_cannot_answer(monkeypatch, tmp_path):
    _, rows, _ = run(monkeypatch, tmp_path, [answer("# CANNOT: no way to write this"), answer("18sc")])
    assert (rows[1].status, rows[1].code, rows[1].origin) == ("cannot", "", "model")
    assert rows[1].note == "no way to write this"
    assert rows[2].status == "ok"


def test_prose_row_gets_empty_code(monkeypatch, tmp_path):
    _, rows, _ = run(monkeypatch, tmp_path, [answer(""), answer("18sc")])
    assert (rows[1].status, rows[1].code) == ("ok", "")


def test_empty_reply_is_cannot_and_not_cached(monkeypatch, tmp_path):
    _, rows, _ = run(monkeypatch, tmp_path, ["", answer("18sc")])
    assert rows[1].status == "cannot"
    assert "no answer" in rows[1].note
    assert len(list(tmp_path.glob("*.json"))) == 1  # only the good reply was cached


def test_invalid_reply_is_cannot(monkeypatch, tmp_path):
    _, rows, _ = run(monkeypatch, tmp_path, ["not json", answer("18sc")])
    assert rows[1].status == "cannot"
    assert "not valid" in rows[1].note


def test_cache_hit_makes_no_second_call(monkeypatch, tmp_path):
    run(monkeypatch, tmp_path, [answer("12sc"), answer("18sc")])
    fake, rows, cost = run(monkeypatch, tmp_path, [])
    assert fake.calls == []
    assert cost == 0
    assert [r.code for r in rows] == ["6sc", "12sc", "18sc"]


def test_synthetic_and_parsed_rows_are_not_sent(monkeypatch, tmp_path):
    rows = make_rows()
    rows[2] = RowResult(index=2, source="added", origin="none", status="flagged", synthetic=True)
    fake, out, _ = run(monkeypatch, tmp_path, [answer("12sc")], rows)
    assert len(fake.calls) == 1
    assert "Translate row 1 now" in fake.calls[0]["prompt"]
    assert out[0].origin == "rules"
    assert out[2].status == "flagged" and out[2].origin == "none"


def test_nothing_flagged_makes_no_call(monkeypatch, tmp_path):
    rows = [make_rows()[0]]
    fake, out, cost = run(monkeypatch, tmp_path, [], rows)
    assert fake.calls == [] and cost == 0 and out == rows
