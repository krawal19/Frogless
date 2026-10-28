"""reconcile_counts(): the count-guided retry, with chat() mocked (no API calls)."""

import json

from frogless.engine import CheckResult, RowInfo
from frogless.pipeline import reconcile, translate
from frogless.pipeline.reconcile import reconcile_counts
from frogless.pipeline.report import RowResult


class FakeEngine:
    """Code lines like "12dc" make one row of that many dc; "ring.R0" makes no row."""

    def notation_guide(self):
        return "GUIDE TEXT"

    def describe(self, code):
        return [f"ENGLISH({line})" for line in code.splitlines() if line.strip()]

    def check(self, code):
        counts = [int(l[:-2]) for l in code.splitlines() if l.endswith("dc")]
        return CheckResult(ok=True, rows=[RowInfo(i + 1, n, {"dc": n}) for i, n in enumerate(counts)])


TEXT = "Round 1: 6 dc in ring (6)\nRound 2: 7dc along each side (8)"


def rows(code2="14dc", source2="Round 2: 7dc along each side (8)"):
    return [
        RowResult(index=0, source="make a magic ring.", code="ring.R0", origin="rules", synthetic=True),
        RowResult(index=1, source="Round 1: 6 dc in ring (6)", code="6dc", origin="rules", faithful=True),
        RowResult(index=2, source=source2, code=code2, origin="model", faithful=True),
    ]


class FakeChat:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, role, messages, **opts):
        self.calls.append({"role": role, "prompt": messages[0]["content"], **opts})
        return {"text": json.dumps(self.replies.pop(0)), "usage": {"input_tokens": 100, "output_tokens": 5},
                "cost_usd": 0.01}


def run(monkeypatch, tmp_path, replies, rows_in=None):
    fake = FakeChat(replies)
    monkeypatch.setattr(translate, "chat", fake)
    out, cost = reconcile_counts(FakeEngine(), TEXT, rows_in or rows(), tmp_path / "r", tmp_path / "f")
    return fake, out, cost


def fix(code="8dc", explanation="the side ends up with 7 dc"):
    return {"code": code, "explanation": explanation}


def judged(kind, reading="", reason=""):
    return {"verdict": kind, "reading": reading, "reason": reason}


def test_accepted_reading_marks_the_row_interpreted(monkeypatch, tmp_path):
    fake, out, cost = run(monkeypatch, tmp_path, [fix(), judged("interpreted", "7 dc per side counting corners", "7dc is a total")])
    assert [c["role"] for c in fake.calls] == ["translator", "faithfulness"]
    assert "says this row has 8, but the current code makes 14" in fake.calls[0]["prompt"]
    assert "the side ends up with 7 dc" in fake.calls[1]["prompt"]  # the checker is told the explanation
    row = out[2]
    assert row.code == "8dc" and row.origin == "model" and row.faithful is True
    assert row.reading == "7 dc per side counting corners" and row.why == "7dc is a total"
    assert row.note.startswith("read as 7 dc per side")
    assert cost == 0.02


def test_faithful_verdict_is_accepted_too(monkeypatch, tmp_path):
    _, out, _ = run(monkeypatch, tmp_path, [fix(), judged("faithful")])
    assert out[2].code == "8dc"
    assert out[2].reading == "the side ends up with 7 dc" and "8" in out[2].why


def test_rejected_by_the_checker_keeps_the_original(monkeypatch, tmp_path):
    for kind in ("mismatch", "cannot_tell"):
        _, out, _ = run(monkeypatch, tmp_path / kind, [fix(), judged(kind, reason="drops stitches")])
        assert out[2].code == "14dc" and out[2].reading == "" and out[2].origin == "model"


def test_same_code_keeps_the_original_and_skips_the_checker(monkeypatch, tmp_path):
    fake, out, _ = run(monkeypatch, tmp_path, [fix("14dc", "no such reading")])
    assert len(fake.calls) == 1
    assert out[2].code == "14dc" and out[2].reading == ""


def test_new_code_that_still_misses_the_count_is_not_checked(monkeypatch, tmp_path):
    fake, out, _ = run(monkeypatch, tmp_path, [fix("10dc")])
    assert len(fake.calls) == 1 and out[2].code == "14dc"


def test_rows_that_already_fit_are_never_sent(monkeypatch, tmp_path):
    fake, out, cost = run(monkeypatch, tmp_path, [], rows("8dc"))
    assert fake.calls == [] and cost == 0 and out[2].code == "8dc"


def test_rows_without_a_stated_count_are_never_sent(monkeypatch, tmp_path):
    fake, _, _ = run(monkeypatch, tmp_path, [], rows("14dc", "Round 2: 7dc along each side"))
    assert fake.calls == []


def test_each_row_is_tried_once(monkeypatch, tmp_path):
    two = rows() + [RowResult(index=3, source="Round 3: dc around (30)", code="20dc", origin="rules")]
    fake, out, _ = run(monkeypatch, tmp_path, [fix("8dc"), judged("interpreted", "r", "w"), fix("20dc", "none")], two)
    assert len(fake.calls) == 3  # row 2: ask + check; row 3: ask (same code, nothing more)
    assert out[3].code == "20dc"
