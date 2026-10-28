"""check_pattern(): the whole Frogless pipeline for one written pattern."""

from dataclasses import replace

from ..engine import Engine, get_engine
from ..patterns.sizes import split_sizes
from ..patterns.terms import Terms, detect_terms, to_us
from .faithful import check_faithfulness
from .ledger import count_ledger
from .reconcile import reconcile_counts
from .report import PatternReport
from .review import review_report
from .shape import check_shape, meant_flat, starts_from_ring
from .translate import rule_rows, translate_flagged
from .verdict import decide_verdict


def check_pattern(text: str, *, engine: Engine | None = None, use_model: bool = True,
                  faithfulness: bool = True, count_retry: bool = True, ledger: bool = True,
                  terms: str = "auto", review: bool = True) -> PatternReport:
    """Translate, verify and judge a pattern. use_model=False makes no model calls.

    ledger: count the rows the engine cannot model (read by the model, added up by our code) instead of
    giving up on them; part of the model steps, so it needs use_model.
    review: when the pattern does not simply work, ask Alice ("it is right as written") and Bob ("it has a mistake")
    and let code referee them; may suggest re-checked fixes. Part of the model steps, so it needs use_model.
    terms: "auto" detects US or UK stitch names; "US" or "UK" chooses. UK is converted to US first.
    """
    original = text
    found, note = _read_terms(text, terms)
    if found.kind == "UK":
        text = to_us(text)
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
    rows = [replace(r, synthetic=True, code="") if engine.is_marker(r.source) else r for r in rows]
    if use_model and ledger:
        rows, spent = count_ledger(engine, text, rows)
        cost += spent

    report = PatternReport(text=original, rows=rows, cost_usd=cost, terms=found)
    if note:
        report.notes.append(note)
    report.check = engine.check(report.code) if report.code else None
    report.verdict, report.stated, report.computed = decide_verdict(engine, text, rows, report.check)
    if use_model and review:
        report.cost_usd += review_report(engine, text, report)
    if report.check:  # hints about the finished piece; they never change the verdict
        report.shape = check_shape(report.check.rows, from_ring=starts_from_ring(text), flat=meant_flat(text))
    return report


def check_pattern_sizes(text: str, **kw) -> list[tuple[str, PatternReport]]:
    """check_pattern() for each size of a multi-size pattern; one (label, report) for a single size."""
    return [(label, check_pattern(part, **kw)) for label, part in split_sizes(text)]


def _read_terms(text: str, terms: str) -> tuple[Terms, str]:
    """The terms to check with and the note to tell the user ("" if none)."""
    choice = terms.upper() if terms.lower() != "auto" else "AUTO"
    if choice in ("US", "UK"):
        found = Terms(choice, ["chosen by you"])
    elif choice == "AUTO":
        found = detect_terms(text)
    else:
        raise ValueError(f"terms must be auto, US or UK, not {terms!r}")
    if found.kind == "UK":
        why = f" ({', '.join(found.evidence)})" if choice == "AUTO" and found.evidence else ""
        return found, f"Read as UK terms{why}; converted to US."
    if found.kind == "unknown" and found.ambiguous:
        return found, ("The pattern doesn't say US or UK and uses only ch/dc/tr, so it was checked as US terms. "
                       "If it's UK, check again with UK terms.")
    return found, ""
