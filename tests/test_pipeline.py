"""check_pattern() without model calls."""

from frogless.pipeline.check import check_pattern

CIRCLE = "Round 1: 6 sc in ring (6)\nRound 2: inc in each st around (12)"


def test_readable_circle_works():
    report = check_pattern(CIRCLE, use_model=False)
    assert report.verdict.kind == "works"
    assert report.cost_usd == 0


def test_unreadable_row_without_a_model():
    report = check_pattern(CIRCLE + "\nRound 3: *sc, inc; rep from * around (18)", use_model=False)
    assert report.verdict.kind == "unreadable"
    assert any(r.status == "flagged" for r in report.rows)
