"""check_pattern(): the whole Frogless pipeline for one written pattern."""

from ..engine import Engine, get_engine
from .faithful import check_faithfulness
from .reconcile import reconcile_counts
from .report import PatternReport
from .shape import check_shape, meant_flat, starts_from_ring
from .translate import rule_rows, translate_flagged
from .verdict import decide_verdict


def check_pattern(text: str, *, engine: Engine | None = None, use_model: bool = True,
                  faithfulness: bool = True, count_retry: bool = True) -> PatternReport:
    """Translate, verify and judge a pattern. use_model=False makes no model calls."""
    engine = engine or get_engine()
    rows, cost = rule_rows(engine, text), 0.0
    if use_model:
        rows, spent = translate_flagged(engine, text, rows)
        cost += spent
        if faithfulness:
            rows, spent = check_faithfulness(engine, text, rows)
            cost += spent
        if count_retry:
            rows, spent = reconcile_counts(engine, text, rows)
            cost += spent

    report = PatternReport(text=text, rows=rows, cost_usd=cost)
    report.check = engine.check(report.code) if report.code else None
    report.verdict, report.stated, report.computed = decide_verdict(engine, text, rows, report.check)
    if report.check:  # hints about the finished piece; they never change the verdict
        report.shape = check_shape(report.check.rows, from_ring=starts_from_ring(text), flat=meant_flat(text))
    return report
