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


def run(monkeypatch, tmp_path, replies, rows=None, samples=1):
    fake = FakeChat(replies)
    monkeypatch.setattr(translate, "chat", fake)
    out, cost = translate_flagged(FakeEngine(), TEXT, rows or make_rows(), cache_dir=tmp_path, samples=samples)
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


def test_a_reply_that_used_the_whole_budget_is_retried_with_the_larger_one(tmp_path, monkeypatch):
    from frogless.pipeline import translate

    calls = []

    def fake_chat(role, messages, **kw):
        calls.append(kw.get("max_tokens"))
        if len(calls) == 1:
            return {"text": "", "usage": {"output_tokens": 4000}, "cost_usd": 0.01}
        return {"text": '{"code": "6sc"}', "usage": {"output_tokens": 900}, "cost_usd": 0.02}

    monkeypatch.setattr(translate, "chat", fake_chat)
    monkeypatch.setattr(translate, "load_config", lambda: {"roles": {"translator": {
        "model": "m", "max_tokens": 4000, "max_tokens_retry": 8000}}})
    reply, cost = translate.ask_cached("x <pattern> y", "translator", translate.ANSWER_SCHEMA, tmp_path, "t")
    assert calls == [None, 8000]
    assert reply["text"] == '{"code": "6sc"}' and round(cost, 2) == 0.03


# ---- several attempts and the referee ----
class RefEngine(FakeEngine):
    """Code like "12sc" is a row of that many sc; "BAD" is invalid code."""

    def check(self, code):
        from types import SimpleNamespace

        if "BAD" in code:
            return SimpleNamespace(ok=False, error=SimpleNamespace(kind="invalid", message="unknown stitch"), rows=[])
        rows = [SimpleNamespace(index=k + 1, stitch_count=int(line.split("sc")[0]), stitch_types={"sc": int(line.split("sc")[0])})
                for k, line in enumerate(code.splitlines())]
        return SimpleNamespace(ok=True, error=None, rows=rows)

    def describe(self, code):
        return [code]


def by_attempt(*codes):
    """A chat that answers by the "Attempt k of n" line, so threads cannot reorder the replies. Attempt 1 has no line."""
    calls = []

    def chat(role, messages, **opts):
        prompt = messages[0]["content"]
        calls.append(prompt)
        k = int(prompt.split("Attempt ")[1].split(" of")[0]) if "Attempt " in prompt.split("Translate row")[-1] else 1
        return {"text": answer(codes[k - 1]), "usage": {"input_tokens": 10, "output_tokens": 5}, "cost_usd": 0.01}

    return chat, calls


def referee_run(monkeypatch, tmp_path, codes, source="Round 2: weird thing one", verdicts=None, **kw):
    from frogless.pipeline import faithful

    chat, calls = by_attempt(*codes)
    judged = []

    def judge(guide, text, row, english, cache_dir, context=""):
        judged.append(row.code)
        verdict = (verdicts or {}).get(row.code, "faithful")
        return {"verdict": verdict, "reading": "", "reason": f"{row.code} is wrong"}, 0.0

    monkeypatch.setattr(translate, "chat", chat)
    monkeypatch.setattr(faithful, "_judge", judge)
    monkeypatch.setattr(faithful, "_english", lambda engine, rows, i: [rows[i].code])
    rows = [RowResult(index=0, source=source, origin="none", status="flagged")]
    out, cost = translate_flagged(RefEngine(), source, rows, cache_dir=tmp_path, judge_cache_dir=tmp_path, **kw)
    return out[0], cost, calls, judged


def test_three_independent_attempts_with_their_own_cache_keys(monkeypatch, tmp_path):
    row, cost, calls, _ = referee_run(monkeypatch, tmp_path, ["6sc", "6sc", "6sc"])
    assert len(calls) == 3 and len(list(tmp_path.glob("*.json"))) == 3
    tails = [c.split("Translate row")[-1] for c in calls]
    assert sum("Attempt" in t for t in tails) == 2 and "Attempt 2 of 3" in "".join(tails) and "Attempt 3 of 3" in "".join(tails)
    assert len({c.split("<pattern>")[0] for c in calls}) == 1  # the static start is the same
    assert row.code == "6sc" and row.status == "ok" and row.origin == "model"
    assert round(cost, 2) == 0.03


def test_the_answer_most_attempts_agree_on_wins(monkeypatch, tmp_path):
    row, _, _, _ = referee_run(monkeypatch, tmp_path, ["7sc", "6sc", "6sc"])
    assert row.code == "6sc"
    assert row.note.startswith("picked attempt 2 of 3") and "2 of 3 attempts agree" in row.note


def test_an_attempt_the_engine_rejects_is_dropped(monkeypatch, tmp_path):
    row, _, _, judged = referee_run(monkeypatch, tmp_path, ["BAD", "BAD", "6sc"])
    assert row.code == "6sc"  # two rejected attempts do not outvote the one valid one
    assert "2 rejected by the engine" in row.note
    assert judged == []  # one valid answer: nothing to choose between


def test_an_attempt_whose_count_fits_is_preferred(monkeypatch, tmp_path):
    row, _, _, _ = referee_run(monkeypatch, tmp_path, ["7sc", "7sc", "6sc"], source="Round 2: weird thing one (6)")
    assert row.code == "6sc"  # the single attempt that makes the stated 6 beats two that agree on 7
    assert "its count fits the stated count" in row.note


def test_the_next_best_is_tried_when_the_check_finds_a_mismatch(monkeypatch, tmp_path):
    row, _, _, judged = referee_run(monkeypatch, tmp_path, ["7sc", "7sc", "6sc"], verdicts={"7sc": "mismatch"})
    assert judged == ["7sc", "6sc"] and row.code == "6sc"
    assert "an earlier pick did not match the row" in row.note
    row, _, _, _ = referee_run(monkeypatch, tmp_path / "b", ["7sc", "8sc", "6sc"],
                               verdicts={"7sc": "mismatch", "8sc": "mismatch", "6sc": "mismatch"})
    assert row.code == "7sc" and row.status == "ok"  # all mismatch: the best stays, the retry loop takes over


def test_the_faithfulness_check_is_only_asked_when_there_is_a_choice(monkeypatch, tmp_path):
    _, _, _, judged = referee_run(monkeypatch, tmp_path, ["6sc", "6sc", "6sc"])
    assert judged == []


def test_one_sample_keeps_the_old_behaviour(monkeypatch, tmp_path):
    row, cost, calls, judged = referee_run(monkeypatch, tmp_path, ["6sc", "7sc", "7sc"], samples=1)
    assert len(calls) == 1 and "Attempt" not in calls[0] and judged == []
    assert row.code == "6sc" and row.note == "" and round(cost, 2) == 0.01


def test_samples_default_comes_from_the_translator_config(monkeypatch):
    assert translate._samples(None) == 3  # config/models.json
    monkeypatch.setattr(translate, "load_config", lambda: {"roles": {"translator": {"samples": 1}}})
    assert translate._samples(None) == 1 and translate._samples(2) == 2
