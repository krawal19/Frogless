"""Check one written crochet pattern and print a readable report.

Run from the repo root:
    python -m scripts.check path/to/pattern.txt [--no-model] [--no-review] [--terms auto|US|UK]

--no-model uses only the rules translator: rows it cannot read stay flagged, no API calls.
"""

import argparse
import sys
from pathlib import Path

from frogless.patterns.sizes import size_count
from frogless.models.client import ROOT
from frogless.pipeline.check import check_pattern, check_pattern_sizes
from frogless.pipeline.messages import fix_lines, shape_lines, user_message


def format_report(report) -> str:
    v = report.verdict
    where = f" (row {v.row})" if v.row is not None else ""
    lines = [user_message(report), ""]
    if report.terms:
        t = report.terms
        shown = t.kind + (" (ambiguous)" if t.ambiguous else "")
        lines += [f"Terms: {shown}" + (f"  [{', '.join(t.evidence)}]" if t.evidence else ""), ""]
    lines += [f"Verdict: {v.kind}{where}", f"  {v.message}"]
    for reading in v.readings:
        lines.append(f"  reading: {reading}")
    for line in fix_lines(report):
        lines.append(f"  {line}")
    if report.review:
        rv = report.review
        lines += [f"Review: {rv.outcome} after {rv.attempts} round(s); Alice {'passed' if rv.alice_passed else 'failed'}, "
                  f"Bob {'passed' if rv.bob_passed else 'failed'}"]
        lines += [f"  Alice: {rv.alice}"] if rv.alice else []
        lines += [f"  Bob: {rv.bob}"] if rv.bob else []
        lines += [f"  rejected: {reason}" for reason in rv.reasons]
    lines.append("")
    lines.append("Rows:")
    for r in report.rows:
        added = " (added)" if r.synthetic else ""
        faithful = "" if r.faithful is None else (" faithful" if r.faithful else " NOT faithful")
        lines.append(f"  [{r.index}] {r.origin}/{r.status}{added}{faithful}  {r.source}")
        lines.append(f"       code: {r.code or '-'}")
        if r.english:
            lines.append(f"       english: {r.english}")
        if r.note:
            lines.append(f"       note: {r.note}")
        if r.ledger_ok is not None:
            lines.append(f"       ledger: uses {r.ledger_uses}, makes {r.ledger_makes}, "
                         f"{'fits' if r.ledger_ok else 'DOES NOT FIT'}: {r.ledger_note}")
        elif r.ledger_note:
            lines.append(f"       ledger: {r.ledger_note}")
    if report.stated or report.computed:
        lines.append("")
        lines.append("Stitch counts (row: stated / computed):")
        for n in sorted(set(report.stated) | set(report.computed)):
            lines.append(f"  {n}: {report.stated.get(n, '-')} / {report.computed.get(n, '-')}")
    for note in report.notes:
        lines.append(f"Note: {note}")
    if report.shape:
        lines.append("")
        lines.append("Shape hints:")
        lines += [f"  {line}" for line in shape_lines(report)]
    lines.append("")
    lines.append(f"Cost: ${report.cost_usd:.4f}")
    return "\n".join(lines)


def print_outputs(report, args, label: str = "") -> None:
    """--clean / --chart: the clean written pattern and the chart image(s), after the report."""
    from frogless.pipeline.output import INSTALL_HINT, chart, clean_pattern

    if args.clean:
        print("Clean pattern:")
        print(clean_pattern(report))
        print()
    if args.chart is not None:
        out = args.chart or ROOT / "logs" / "charts" / args.pattern.stem
        out = Path(out) / "".join(c if c.isalnum() or c in "-_" else "_" for c in label) if label else Path(out)
        try:
            drawn = chart(report, out)
        except ImportError:
            print(INSTALL_HINT)
            return
        shown = [(k, drawn[k]) for k in ("chart", "view") if drawn.get(k)]
        for what, path in shown:
            print(f"{'Chart' if what == 'chart' else '3D view'}: {path}")
        if drawn.get("note"):
            print(drawn["note"])
        if drawn.get("error"):
            print(f"Could not draw the pattern: {drawn['error']}")
        print()


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pattern", type=Path, help="text file with the pattern")
    parser.add_argument("--no-model", action="store_true", help="rules translator only, no API calls")
    parser.add_argument("--no-ledger", action="store_true",
                        help="do not count (with the model's help) the rows the engine cannot model")
    parser.add_argument("--no-review", action="store_true",
                        help="do not ask Alice and Bob (model) about a pattern that does not simply work")
    parser.add_argument("--terms", choices=["auto", "US", "UK"], default="auto",
                        help="stitch names: detect (default), or force US or UK")
    parser.add_argument("--clean", action="store_true", help="also print the clean written pattern")
    parser.add_argument("--chart", nargs="?", const="", metavar="DIR",
                        help="also draw the crochet chart (or the 3D view for clearly 3D pieces) into DIR "
                             "(default logs/charts/<pattern name>/); needs Playwright")
    args = parser.parse_args()
    text = args.pattern.read_text(encoding="utf-8")
    opts = {"use_model": not args.no_model, "terms": args.terms, "ledger": not args.no_ledger,
            "review": not args.no_review}
    if size_count(text) == 1:
        report = check_pattern(text, **opts)
        print(format_report(report))
        print_outputs(report, args)
        return
    for label, report in check_pattern_sizes(text, **opts):
        print(f"===== {label} =====")
        print(format_report(report))
        print()
        print_outputs(report, args, label)


if __name__ == "__main__":
    main()
