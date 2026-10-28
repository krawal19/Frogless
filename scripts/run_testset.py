"""Run the known-answer test bench.

Run from the repo root: python -m scripts.run_testset [--patterns FOLDER [--summary-only]]

Synthetic cases go through three routes: code (spec -> encode -> check), English
(English -> translate -> stated-count gate -> check) and verdict (encoded code paired with the
case's English rows -> decide_verdict, which also compares each row's stated count with the
count the engine makes). Each route is PASS / FAIL / UNREADABLE per case.
--patterns runs only the English route on a folder of real pattern .txt files, which
have no known answer. --summary-only prints totals only (for a held-out set).
Output: a summary on screen and logs/testset/*.json. No model calls.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from frogless.engine import get_engine
from frogless.pipeline.gate import gate_translation
from frogless.pipeline.report import RowResult
from frogless.pipeline.verdict import decide_verdict
from frogless.testset.generators import ROOT, base_cases, load_config
from frogless.testset.inject import injected_cases

ROUTES = ("code", "english", "verdict")


def counts_of(result):
    """Stitches made per row, without turning chains and the foundation chain row."""
    return [r.stitch_count - r.stitch_types.get("ch", 0) for r in result.rows if r.index >= 1]


def judge(expected, result) -> tuple[str, str]:
    """Compare a check result with the known answer: (PASS|FAIL, short reason)."""
    got = "works" if result.ok else "breaks"
    row = None if result.ok else result.error.row
    if got != expected["verdict"]:
        why = f"engine says {got}" + (f" at row {row}: {result.error.message[:60]}" if row else "")
        return "FAIL", f"expected {expected['verdict']}, {why}"
    if got == "breaks" and row != expected["break_row"]:
        return "FAIL", f"broke at row {row}, expected row {expected['break_row']}"
    if got == "works" and counts_of(result) != expected["counts"]:
        return "FAIL", f"counts {counts_of(result)}, expected {expected['counts']}"
    return "PASS", ""


def run_code(engine, case):
    code = engine.encode(case["spec"])
    case["code"] = code
    return judge(case["expected"], engine.check(code))


def run_english(engine, case):
    tr = gate_translation(engine, engine.translate(case["english"]), case["english"])
    case["translated"] = tr.code
    bad = [l for l in tr.lines if not l.parsed and not l.synthetic]
    if bad:
        return "UNREADABLE", f"{len(bad)} of {len(tr.lines)} lines unparsed: {bad[0].reason[:70]}"
    return judge(case["expected"], engine.check(tr.code))


_LABEL = re.compile(r"^\s*\w+?\s*(\d+)(?:\s*-\s*(\d+))?\s*:")


def verdict_rows(engine, case) -> list[RowResult]:
    """Rows for decide_verdict: the encoded code, one line per row, paired with the English line
    it came from (a range line such as "R2-8" covers several code lines)."""
    spec, code = case["spec"], engine.encode(case["spec"]).splitlines()
    english = case["english"].splitlines()
    rows = []
    if spec.start == "ring":  # the encoder's first line only makes the ring; no English of its own
        rows.append(RowResult(index=0, source="make a magic ring.", code=code.pop(0), synthetic=True))
    for line in english:
        m = _LABEL.match(line)  # "Ch 11." has no number-colon label: it is the foundation chain, one line
        n = int(m[2]) - int(m[1]) + 1 if m and m[2] else 1
        for _ in range(n):
            rows.append(RowResult(index=len(rows), source=line, code=code.pop(0)))
    assert not code, "more code lines than English rows"
    return rows


def run_verdict(engine, case):
    rows = verdict_rows(engine, case)
    code = "\n".join(r.code for r in rows)
    verdict, _, _ = decide_verdict(engine, case["english"], rows, engine.check(code))
    case["verdict"] = {"kind": verdict.kind, "row": verdict.row, "message": verdict.message}
    want, row = case["expected"]["verdict"], case["expected"]["break_row"]
    if verdict.kind != want:
        return "FAIL", f"expected {want}, verdict {verdict.kind}: {verdict.message[:70]}"
    if want == "breaks" and verdict.row != row:
        return "FAIL", f"broke at row {verdict.row}, expected row {row}"
    return "PASS", ""


def run_synthetic(engine, cfg):
    cases = base_cases(cfg)
    cases += injected_cases(cfg, cases)
    for case in cases:
        case["results"] = {}
        for route, fn in zip(ROUTES, (run_code, run_english, run_verdict)):
            status, reason = fn(engine, case)
            case["results"][route] = {"status": status, "reason": reason}
        res = case["results"]
        gap = " [known_gap]" if case["known_gap"] else ""
        print(f"{case['id']:<44}{gap:<13} code {res['code']['status']:<10} english {res['english']['status']:<11}"
              f" verdict {res['verdict']['status']}")
        for route in ROUTES:
            if res[route]["reason"]:
                print(f"    {route}: {res[route]['reason']}")
    return cases


def tally(cases, key):
    """{group: {route: {status: n}}} for cases grouped by key(case)."""
    out = defaultdict(lambda: {r: defaultdict(int) for r in ROUTES})
    for c in cases:
        for route in ROUTES:
            out[key(c)][route][c["results"][route]["status"]] += 1
    return out


def fmt(counts):
    total = sum(counts.values())
    pct = 100 * counts.get("PASS", 0) // total if total else 0
    return f"{counts.get('PASS', 0)}/{total} pass ({pct}%), {counts.get('FAIL', 0)} fail, {counts.get('UNREADABLE', 0)} unreadable"


def reason_key(reason):
    """Group similar reasons: drop numbers and any pattern text."""
    if "REVIEW[" in reason:
        reason = reason.split("]")[0]
    elif reason.startswith("broke at row"):
        reason = "broke at the wrong row"
    reason = re.sub(r"^\d+ of \d+ lines unparsed: ", "", reason)
    return re.sub(r"\d+", "N", reason)[:60]


def print_summary(cases):
    print("\n=== Summary ===")
    sections = [
        ("all cases", lambda c: "all"),
        ("by family (working cases)", lambda c: c["family"] if not c["injection"] else None),
        ("by injection type", lambda c: c["injection"]),
        ("known_gap", lambda c: "known_gap" if c["known_gap"] else None),
    ]
    for title, key in sections:
        print(f"\n{title}")
        groups = tally([c for c in cases if key(c)], key)
        for name, per_route in sorted(groups.items()):
            print(f"  {name:<22}" + "".join(f"\n      {r:<8}{fmt(per_route[r])}" for r in ROUTES))
    print("\ntop reasons for FAIL / UNREADABLE")
    for r in ROUTES:
        reasons = defaultdict(int)
        for c in cases:
            res = c["results"][r]
            if res["status"] != "PASS":
                reasons[f"{res['status']}: {reason_key(res['reason'])}"] += 1
        for why, n in sorted(reasons.items(), key=lambda kv: -kv[1])[:5]:
            print(f"      {r:<8}{n:>3}  {why}")
    # Pass rates without the known-gap cases, so the gap does not hide real failures
    rest = [c for c in cases if not c["known_gap"]]
    print("\nwithout known_gap cases")
    for r in ROUTES:
        print(f"      {r:<8}{fmt(tally(rest, lambda c: 'x')['x'][r])}")


def pattern_rows(engine, text):
    tr = gate_translation(engine, engine.translate(text), text)
    lines = [l for l in tr.lines if not l.synthetic]
    parsed = sum(l.parsed for l in lines)
    check = engine.check(tr.code) if tr.code else None
    return tr, lines, parsed, check


def run_folder(engine, folder, summary_only):
    names = sorted(p.stem for p in folder.glob("*.txt"))
    results = []
    for name in names:
        tr, lines, parsed, check = pattern_rows(engine, (folder / f"{name}.txt").read_text(encoding="utf-8"))
        ok = bool(check and check.ok)
        row = {"pattern": name, "rows": len(lines), "parsed": parsed,
               "pct_translated": round(100 * parsed / len(lines)) if lines else 0,
               "check_ok_on_translated": ok}
        if not summary_only:
            row["error"] = None if ok or not check else f"row {check.error.row}: {check.error.message[:80]}"
            row["lines"] = [{"row": i, "parsed": l.parsed, "reason": reason_key(l.reason)} for i, l in enumerate(lines, 1)]
            print(f"{name}: {parsed}/{len(lines)} rows translated ({row['pct_translated']}%), "
                  f"check on translated part: {'ok' if ok else row['error'] or 'nothing to check'}")
            for l in row["lines"]:
                if not l["parsed"]:
                    print(f"    row {l['row']}: {l['reason']}")
        results.append(row)
    if summary_only:
        n = len(results)
        total, parsed = sum(r["rows"] for r in results), sum(r["parsed"] for r in results)
        print(f"{folder.name}: {n} patterns, {parsed}/{total} rows translated "
              f"({100 * parsed // total if total else 0}%), check ok on translated part: "
              f"{sum(r['check_ok_on_translated'] for r in results)}/{n}")
        results = [{"patterns": n, "rows": total, "parsed": parsed,
                    "check_ok": sum(r["check_ok_on_translated"] for r in results)}]
    return results


def write_report(cfg, payload):
    path = ROOT / cfg["report"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\nReport: {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--patterns", type=Path, help="folder of real pattern .txt files (English route only)")
    parser.add_argument("--summary-only", action="store_true", help="with --patterns: print totals only")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg, engine = load_config(), get_engine()

    if args.patterns:
        if not args.patterns.is_dir():
            parser.error(f"not a folder: {args.patterns}")
        results = run_folder(engine, args.patterns, args.summary_only)
        write_report({**cfg, "report": str(Path(cfg["report"]).with_name(f"patterns_{args.patterns.name}.json"))},
                     {"folder": args.patterns.name, "results": results})
        return
    cases = run_synthetic(engine, cfg)
    print_summary(cases)
    slim = [{k: v for k, v in c.items() if k not in ("spec", "style")} for c in cases]
    write_report(cfg, {"seed": cfg["seed"], "cases": slim})


if __name__ == "__main__":
    main()
