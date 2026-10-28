"""clean_pattern() and chart(): the written pattern and the picture the user gets after the verdict.

Reports come from the rules translator (no model calls); the checks look only at the text a
crocheter would read, never at engine syntax.
"""

import pytest

from frogless.pipeline import output
from frogless.pipeline.check import check_pattern
from frogless.pipeline.output import INSTALL_HINT, chart, clean_pattern
from frogless.pipeline.report import Interpreted, Verdict
from frogless.pipeline.shape import ShapeFinding

CIRCLE = """R1: 6 sc in magic ring (6)
R2: inc in each st around (12)
R3: (sc, inc) 6 times (18)
R4: sc in each st around (18)
R5: sc in each st around (18)"""

ENGINE_SYNTAX = ("@R0", "sc2inc", "*[", "ring.R", "6sc", ",turn")


def report(text, **kw):
    return check_pattern(text, use_model=False, **kw)


def test_counts_are_appended_to_each_round():
    text = clean_pattern(report(CIRCLE))
    lines = text.splitlines()
    assert lines[0] == "Make a magic ring."
    assert lines[1] == "Round 1: 6 sc in magic ring. (6)"
    assert lines[2].endswith("(12)") and lines[3].endswith("(18)")


def test_rounds_that_read_the_same_are_one_line():
    text = clean_pattern(report(CIRCLE))
    assert "Rounds 4-5: sc in next 18 sts. (18)" in text


def test_no_engine_syntax_is_shown():
    text = clean_pattern(report(CIRCLE))
    assert not [bad for bad in ENGINE_SYNTAX if bad in text]


def test_interpreted_row_gets_a_short_note():
    rep = report(CIRCLE)
    rep.verdict.interpreted = [Interpreted(3, "R3", "sc then 2 sc in the same st, six times", "unclear")]
    lines = clean_pattern(rep).splitlines()
    assert any(l.startswith("Round 3:") and "(read as: sc then 2 sc in the same st, six times)" in l for l in lines)


def test_unreadable_row_is_kept_as_written():
    text = "R1: 6 sc in magic ring (6)\nR2: work the fiddly bit as you like (12)\nR3: sc around (12)"
    out = clean_pattern(report(text))
    assert "Round 2: work the fiddly bit as you like (12) [not checked]" in out
    assert "could not read every row" in out
    assert not [bad for bad in ENGINE_SYNTAX if bad in out]


def test_rows_after_a_break_are_written_as_given():
    rep = report(CIRCLE)
    rep.verdict = Verdict("breaks", "Round 2 has 12 stitches, the pattern says 13", row=2)
    out = clean_pattern(rep)
    assert "this pattern breaks at Round 2: Round 2 has 12 stitches" in out
    assert "Round 2: 2 sc in each of next 6 sts. (12) [the pattern breaks here]" in out
    assert "Round 3: (sc, inc) 6 times (18) [not checked: the pattern breaks at Round 2]" in out
    assert "Round 1: 6 sc in magic ring. (6)" in out


def test_flat_rows_keep_their_labels_and_skip_the_foundation_count():
    text = ("Ch 11.\nRow 1: sc in 2nd ch from hook and each ch across (10)\n"
            "Row 2: sc in each st across (10)")
    out = clean_pattern(report(text))
    lines = out.splitlines()
    assert lines[0].startswith("Ch ") and "(" not in lines[0]
    assert lines[1].startswith("Row 1:") and lines[1].endswith("(10)")
    assert lines[2].startswith("Row 2:")


# ---- chart ----
def shape(kind):
    return [ShapeFinding(3, kind, "x", "info")]


def test_clearly_3d_pieces_get_the_3d_view_and_flat_ones_the_chart():
    rep = report(CIRCLE)
    for kind in ("ball", "cups", "tube"):
        rep.shape = shape(kind)
        assert output._kind(rep) == "3d"
    for found in ([], shape("flat_circle")):
        rep.shape = found
        assert output._kind(rep) == "chart"


def test_missing_playwright_gives_install_advice(monkeypatch):
    class NoBrowser:
        def render(self, code, out_dir):
            raise RuntimeError("rendering needs Playwright: see README")

    monkeypatch.setattr(output, "get_engine", lambda: NoBrowser())
    result = chart(report(CIRCLE), "unused")
    assert result["error"] == INSTALL_HINT
    assert result["chart"] is None and result["view"] is None


def test_nothing_to_draw_when_no_row_was_read(tmp_path):
    result = chart(report("R1: do the thing the old way"), tmp_path)
    assert result["error"] == "nothing to draw"


def browser_available():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch().close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not browser_available(), reason="Playwright or Chromium is not installed")
def test_chart_is_drawn_for_a_flat_circle(tmp_path):
    rep = report(CIRCLE.split("\nR4")[0])
    result = chart(rep, tmp_path)
    assert result["error"] is None
    assert result["kind"] == "chart" and result["view"] is None
    assert result["chart"] and (tmp_path / "render_chart.png").is_file()
