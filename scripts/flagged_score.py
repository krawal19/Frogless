"""Score a model's translations of flagged lines (see scripts/flagged_export.py).

Run from the repo root:
    python -m scripts.flagged_score [--dir DIR] [--answers FILE]

Reads DIR/input.json, DIR/key.json and the answers file (default DIR/answers.json):
    {"<pattern id>": {"<row>": "<engine code>" | "# CANNOT: <reason>"}, ...}
Each pattern's code is the translator's rows plus the model's rows, checked by the
engine. Synthetic patterns are judged against the key (PASS / FAIL / UNREADABLE).
Every answered row is also turned back into English so it can be compared with the
original by eye. Writes DIR/score.json. No model calls.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from frogless.engine import get_engine
from frogless.testset.generators import ROOT
from scripts.run_testset import judge


def score_item(engine, item, answers, expected):
    code_lines, answered, cannot = [], [], []
    for r in item["rows"]:
        if not r["flagged"]:
            code_lines.append(r["code"])
            continue
        code = (answers.get(str(r["row"])) or "# CANNOT: no answer").strip()
        if code.startswith("# CANNOT"):
            cannot.append({"row": r["row"], "text": r["text"], "reason": code})
            continue
        code_lines.append(code)
        try:
            english = " ".join(engine.describe(code))
        except Exception as e:  # describe only knows part of the syntax
            english = f"(describe failed: {e})"
        answered.append({"row": r["row"], "text": r["text"], "code": code, "back_to_english": english})

    out = {"id": item["id"], "answered": answered, "cannot": cannot}
    if cannot:
        out["status"], out["reason"] = "UNREADABLE", f"{len(cannot)} rows marked CANNOT"
        return out
    result = engine.check("\n".join(c for c in code_lines if c))
    out["check"] = "works" if result.ok else f"breaks at row {result.error.row}: {result.error.message[:80]}"
    if expected is None:
        out["status"], out["reason"] = "NO KEY", out["check"]
    else:
        out["status"], out["reason"] = judge(expected, result)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, default=ROOT / "logs" / "flagged")
    parser.add_argument("--answers", type=Path)
    args = parser.parse_args()

    items = json.loads((args.dir / "input.json").read_text(encoding="utf-8"))
    key = json.loads((args.dir / "key.json").read_text(encoding="utf-8"))
    answers = json.loads((args.answers or args.dir / "answers.json").read_text(encoding="utf-8"))

    engine = get_engine()
    results = [score_item(engine, it, answers.get(it["id"], {}), key.get(it["id"])) for it in items]

    synthetic = [r for r in results if r["id"] in key]
    tally = Counter(r["status"] for r in synthetic)
    print(f"synthetic: {tally['PASS']}/{len(synthetic)} PASS, {tally['FAIL']} FAIL, {tally['UNREADABLE']} UNREADABLE")
    for r in results:
        if r["status"] != "PASS":
            print(f"  {r['status']:<10} {r['id']}: {r['reason']}")
    (args.dir / "score.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"\nDetails: {args.dir / 'score.json'}")


if __name__ == "__main__":
    main()
