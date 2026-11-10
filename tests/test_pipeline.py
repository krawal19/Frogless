"""check_pattern() without model calls."""

from frogless.pipeline.check import check_pattern

CIRCLE = "Round 1: 6 sc in ring (6)\nRound 2: inc in each st around (12)"


def test_readable_circle_works():
    report = check_pattern(CIRCLE, use_model=False)
    assert report.verdict.kind == "works"
    assert report.cost_usd == 0


def test_unreadable_row_without_a_model():
    # 12 stitches are not whole repeats of 5, so the wording is left for the model
    report = check_pattern(CIRCLE + "\nRound 3: *sc in next 4 sts, inc; rep from * around (15)", use_model=False)
    assert report.verdict.kind == "unreadable"
    assert any(r.status == "flagged" for r in report.rows)


def test_shape_hints_are_reported_apart_from_the_verdict():
    from frogless.pipeline.messages import shape_lines, user_message

    ring = "Round 1: 6 sc in a magic ring (6)\nRound 2: inc in each st around (12)\nRound 3: 12 sc (12)"
    report = check_pattern(ring, use_model=False)
    assert report.verdict.kind == "works"
    assert report.shape and all(f.message in " ".join(shape_lines(report)) for f in report.shape)
    assert "cup" not in user_message(report) and "tube" not in user_message(report)
    # no ring in the text: no circle hints
    assert not any(f.kind in {"flat_circle", "cups"} for f in check_pattern(
        ring.replace("magic ring", "row"), use_model=False).shape)


def test_colour_change_row_keeps_round_numbers():
    text = ("Round 1: 6 sc in ring (6)\nRound 2: inc in each st around (12)\nRound 3: sc around (12)\n"
            "\nChange to white yarn.\n\nRound 4: sc around (14)\nRound 5: sc around (12)")
    report = check_pattern(text, use_model=False)
    assert report.verdict.row == 4  # the colour change is not a row


def test_failed_review_keeps_the_verdict(monkeypatch):
    from frogless.models.client import ProviderError
    from frogless.pipeline import check

    def timed_out(*args, **kwargs):
        raise ProviderError("network error: ReadTimeout: timed out", retryable=True)

    monkeypatch.setattr(check, "translate_flagged", lambda engine, text, rows: (rows, 0.0))
    monkeypatch.setattr(check, "check_faithfulness", lambda engine, text, rows: (rows, 0.0))
    monkeypatch.setattr(check, "reconcile_counts", lambda engine, text, rows: (rows, 0.0))
    monkeypatch.setattr(check, "count_ledger", lambda engine, text, rows: (rows, 0.0))
    monkeypatch.setattr(check, "review_report", timed_out)
    report = check.check_pattern(CIRCLE + "\nRound 3: sc around (14)")
    assert report.verdict.kind == "unreadable"  # the count gate flags the wrong stated count; the model is mocked
    assert any("review step couldn't finish" in n and "took too long" in n for n in report.notes)
