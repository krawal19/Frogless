"""Check one written crochet pattern and print a readable report.

Run from the repo root:
    python -m scripts.check path/to/pattern.txt [--no-model]

--no-model uses only the rules translator: rows it cannot read stay flagged, no API calls.
"""

import argparse
from pathlib import Path

from frogless.pipeline.check import check_pattern


def format_report(report) -> str:
    v = report.verdict
    where = f" (row {v.row})" if v.row is not None else ""
    lines = [f"Verdict: {v.kind}{where}", f"  {v.message}"]
    for reading in v.readings:
        lines.append(f"  reading: {reading}")
    lines.append("")
    lines.append("Rows:")
    for r in report.rows:
        added = " (added)" if r.synthetic else ""
        faithful = "" if r.faithful is None else (" faithful" if r.faithful else " NOT faithful")
        lines.append(f"  [{r.index}] {r.origin}/{r.status}{added}{faithful}  {r.source}")
        lines.append(f"       code: {r.code or '-'}")
        if r.note:
            lines.append(f"       note: {r.note}")
    if report.stated or report.computed:
        lines.append("")
        lines.append("Stitch counts (row: stated / computed):")
        for n in sorted(set(report.stated) | set(report.computed)):
            lines.append(f"  {n}: {report.stated.get(n, '-')} / {report.computed.get(n, '-')}")
    for note in report.notes:
        lines.append(f"Note: {note}")
    lines.append("")
    lines.append(f"Cost: ${report.cost_usd:.4f}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pattern", type=Path, help="text file with the pattern")
    parser.add_argument("--no-model", action="store_true", help="rules translator only, no API calls")
    args = parser.parse_args()
    text = args.pattern.read_text(encoding="utf-8")
    print(format_report(check_pattern(text, use_model=not args.no_model)))


if __name__ == "__main__":
    main()
