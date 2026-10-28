"""Export every synthetic test case with Frogless's full answer, for a crocheter to review.

Run from the repo root:
    python -m scripts.review_export [--max-cost USD] [--out FILE]

For each case: the pattern text, what we expected (worked out by arithmetic), what Frogless
said, and row by row: who translated it (rules or model), the code, the code read back as
English, the stated and computed counts, and the faithfulness checker's note. Model replies
are cached on disk, so a rerun costs nothing. Writes logs/review/review.json by default.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from frogless.engine import get_engine
from frogless.pipeline.check import check_pattern
from frogless.pipeline.messages import user_message
from frogless.pipeline.verdict import READINGS
from frogless.testset.generators import ROOT, base_cases, load_config
from frogless.testset.inject import injected_cases


def export_case(engine, case, use_model):
    report = check_pattern(case["english"], engine=engine, use_model=use_model, review=False)
    v = report.verdict
    written = [r for r in report.rows if not r.synthetic]
    # Same numbering as the verdict: a foundation chain is row 0, a magic-ring round starts at 1.
    first = report.check.rows[0].index if report.check and report.check.rows else 1
    numbers = {id(r): first + n for n, r in enumerate(written)}
    rows = []
    for r in report.rows:
        n = numbers.get(id(r))
        rows.append({
            "number": n, "text": r.source, "added_by_translator": r.synthetic,
            "translated_by": {"rules": "rules", "model": "AI", "none": "nobody"}[r.origin],
            "status": r.status, "code": r.code, "read_back": r.english,
            "stated": report.stated.get(n), "computed": report.computed.get(n),
            "faithful": r.faithful, "note": r.note,
        })
    return {
        "id": case["id"], "family": case["family"], "injection": case.get("injection"),
        "known_gap": case["known_gap"], "input": case["english"],
        "expected": case["expected"],
        "output": {"kind": v.kind, "row": v.row, "message": user_message(report),
                   "reading": v.reading, "interpreted": [i.__dict__ for i in v.interpreted]},
        "rows": rows, "cost_usd": report.cost_usd,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-cost", type=float, default=2.0, help="stop using the model after this many USD")
    parser.add_argument("--out", type=Path, default=ROOT / "logs" / "review" / "review.json")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg, engine = load_config(), get_engine()
    bases = base_cases(cfg)
    cases, spent = [], 0.0
    for case in bases + injected_cases(cfg, bases):
        use_model = spent < args.max_cost
        out = export_case(engine, case, use_model)
        out["model_used"] = use_model
        spent += out["cost_usd"]
        cases.append(out)
        print(f"{case['id']:<44} {out['output']['kind']:<17} ${spent:.2f}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"readings": list(READINGS), "cases": cases}, indent=1), encoding="utf-8")
    print(f"{len(cases)} cases, ${spent:.2f} spent -> {args.out}")


if __name__ == "__main__":
    main()
