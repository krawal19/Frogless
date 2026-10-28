"""Step 5: Alice and Bob, with a code referee.

When a pattern ends in "breaks", "unreadable" or "ambiguous" (or a row could not be read), the model is
asked the same question from two sides, each time about the whole pattern:
- Alice: "the pattern is correct as written; give code that reads every row so the whole pattern works".
  Her rows are "ok" (the literal reading) or "reading" (a genuine but non-literal reading of the words).
- Bob: "the pattern has a mistake; for each row say ok, or fix: the smallest change to the written text that
  makes the whole pattern work". A fix may be in an EARLIER row than the one that breaks.

The referee is code, not AI. For each story it
1. throws away every entry whose quote is not word for word in its row;
2. assembles the whole pattern's code (the current code where the story changed nothing) and runs the engine
   and decide_verdict (stated counts, readings): the story must come out as works;
3. sends every changed row to the faithfulness checker: Alice's rows and Bob's non-fix rows against the row as
   written, Bob's fixes against the fixed text (and the fixed text must differ from the written one).
   A fix is never judged against the written text: it is a fix by definition.
A story passes only if all of that holds. Then:
- Alice passes and reads everything literally: it works (Bob's fix was a false alarm).
- Alice passes with readings and Bob passes too: ambiguous (works under the readings; literally a row is wrong).
- Alice passes with readings, Bob fails: works with interpretations.
- Alice fails, Bob passes: breaks, at the earliest row Bob fixed, with the fixes that were re-checked.
- Both fail: both are asked again, told the referee's reasons, up to MAX_ATTEMPTS in all; then the pipeline's
  own verdict stands.
Fixes that are not needed for the story to pass are dropped, so the ones shown are the smallest set.
Rows counted by the ledger have no engine code to check and are never changed.
"""

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..engine import Engine
from ..models.client import ROOT
from .faithful import CACHE_DIR as FAITHFUL_CACHE_DIR
from .faithful import _english, _judge, _with_answer
from .report import Fix, PatternReport, Review, RowResult, Verdict
from .translate import _rows_listing, ask_cached
from .verdict import _map_rows, decide_verdict

ROLE = "reviewer"
PROMPT = ROOT / "frogless" / "prompts" / "review.md"
TASKS = {"alice": ROOT / "frogless" / "prompts" / "review_alice.md",
         "bob": ROOT / "frogless" / "prompts" / "review_bob.md"}
CACHE_DIR = ROOT / "logs" / "cache" / "review"
MAX_ATTEMPTS = 3  # rounds of asking in all, the first included
PASSING = ("works", "works_unverified", "works_counts_only")  # verdicts under which a story passes
VERDICTS = {"alice": ("ok", "reading"), "bob": ("ok", "reading", "fix")}
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "row": {"type": "integer"},
                    "quote": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["ok", "reading", "fix"]},
                    "code": {"type": "string"},
                    "explanation": {"type": "string"},
                    "fixed_text": {"type": "string"},
                },
                "required": ["row", "quote", "verdict", "code", "explanation", "fixed_text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "rows"],
    "additionalProperties": False,
}
_TOTALS = ('A number written beside a side or a stitch ("7dc") may be what that side comes to in total, counting the '
           'stitches that belong to the corners: reading it so is "interpreted", not a change of the number. ')
_READING_CONTEXT = (
    'The reviewer read this row in a way that may differ from the most literal reading: "{explanation}". '
    'Judge whether the code is a genuinely possible reading of the written words that keeps every stitch, chain '
    'and number the row names: then answer "interpreted" (put the reading in "reading" and what is unclear in '
    '"reason"), or "faithful" if it is the plain reading. ' + _TOTALS +
    'If it changes a stitch type, adds or drops a stitch or chain the row names, skips, merges or ignores an '
    'instruction the row gives (even one that repeats another instruction), or moves stitches somewhere the words '
    'do not allow, answer "mismatch", even if that would make the pattern work.')
_FIX_CONTEXT = (
    "The written row below was edited by a reviewer to repair a mistake in the designer's text (\"{explanation}\"). "
    'Judge the code against the edited text exactly as it is written here. ' + _TOTALS)


@dataclass
class Entry:
    row: int  # position in report.rows
    quote: str
    verdict: str  # "ok", "reading" or "fix"
    code: str  # engine code, or "same"
    explanation: str
    fixed_text: str = ""


@dataclass
class Story:
    """One side's answer after the referee has been through it."""

    who: str
    summary: str = ""
    kept: list[Entry] = field(default_factory=list)  # entries that survived the referee's first look
    reasons: list[str] = field(default_factory=list)  # why entries or the whole story were rejected
    passed: bool = False
    rows: list[RowResult] = field(default_factory=list)  # the assembled rows (with the checker's answers)
    fixes: list[Entry] = field(default_factory=list)  # Bob's fixes that the story needs
    verdict: Verdict | None = None
    stated: dict[int, int] = field(default_factory=dict)
    computed: dict[int, int] = field(default_factory=dict)
    check: object = None
    cost: float = 0.0

    @property
    def literal(self) -> bool:
        return self.passed and self.verdict is not None and not self.verdict.interpreted


def _squash(text: str) -> str:
    return " ".join(text.lower().split())


def needs_review(report: PatternReport) -> bool:
    """Whether the pattern did not simply work, so that Alice and Bob should look at it."""
    v = report.verdict
    if v is None or (v.kind == "breaks" and v.ledger):  # a row counted by AI, not modelled: nothing to re-check
        return False
    if v.kind in ("breaks", "unreadable", "ambiguous"):
        return True
    return any(not r.synthetic and r.ledger_ok is None and (r.status == "cannot" or r.faithful is False)
               for r in report.rows)


# ---- reading and vetting the model's answer ----
def read_reply(text: str) -> tuple[str, list[Entry]] | str:
    """(summary, entries) from the model's reply, or the reason it cannot be read."""
    try:
        raw = json.loads(text)
        summary, items = str(raw.get("summary", "")).strip(), raw["rows"]
        if not isinstance(items, list):
            raise TypeError
    except (ValueError, KeyError, TypeError, AttributeError):
        return "the reply was not valid JSON with a list of rows"
    entries = []
    for item in items:
        try:
            entries.append(Entry(int(item["row"]), str(item["quote"]), str(item["verdict"]).strip().lower(),
                                 str(item["code"]).strip(), str(item["explanation"]).strip(),
                                 str(item.get("fixed_text", "")).strip()))
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return summary, entries


def _keeps(entry: Entry) -> bool:
    return entry.code.lower() in ("same", "")


def vet(who: str, rows: list[RowResult], entries: list[Entry]) -> tuple[list[Entry], list[str]]:
    """The entries that change something and pass the referee's first look, and why the others do not."""
    kept, reasons, seen = [], [], set()
    for e in entries:
        if e.verdict not in VERDICTS[who]:
            reasons.append(f"Row {e.row}: the verdict '{e.verdict}' is not allowed for you; use one of "
                           f"{', '.join(VERDICTS[who])}")
            continue
        if not 0 <= e.row < len(rows) or rows[e.row].synthetic:
            reasons.append(f"Row {e.row} is not a row of the pattern")
            continue
        row = rows[e.row]
        if row.ledger_ok is not None:
            reasons.append(f"Row {e.row} was counted separately and cannot be changed")
            continue
        if e.verdict != "fix" and _keeps(e):
            continue  # says nothing needs to change here
        if e.row in seen:
            continue
        if not e.quote.strip() or _squash(e.quote) not in _squash(row.source):
            reasons.append(f"Row {e.row}: the quote '{e.quote.strip()[:80]}' is not in the row, word for word")
            continue
        if e.code.startswith("#"):
            reasons.append(f"Row {e.row}: give engine code for the row, not a comment")
            continue
        if e.verdict == "fix":
            if not e.fixed_text or _squash(e.fixed_text) == _squash(row.source):
                reasons.append(f"Row {e.row}: a fix must give fixed_text that differs from the written row")
                continue
            if _keeps(e) and not row.code:
                reasons.append(f"Row {e.row}: this row has no code yet; give the code for the fixed text")
                continue
        seen.add(e.row)
        kept.append(e)
    return kept, reasons


# ---- assembling a story ----
def _assemble(rows: list[RowResult], entries: list[Entry], answers: dict[int, RowResult] | None = None
              ) -> list[RowResult]:
    """The rows with the entries applied. `answers` holds rows already judged (their faithful fields are kept)."""
    out = list(rows)
    for e in entries:
        row = rows[e.row]
        code = row.code if _keeps(e) else e.code
        source = e.fixed_text if e.verdict == "fix" else row.source
        if code == row.code and source == row.source:
            continue
        trial = replace(row, code=code, source=source, origin="model", status="ok", note="", english="",
                        faithful=None, reading="", why="")
        judged = (answers or {}).get(e.row)
        if judged is not None and judged.code == code and judged.source == source:
            trial = judged
        out[e.row] = trial
    return out


def _passes(engine: Engine, text: str, rows: list[RowResult]):
    """(verdict, stated, computed, check) of the rows as assembled."""
    code = "\n".join(r.code for r in rows if r.code)
    check = engine.check(code) if code else None
    verdict, stated, computed = decide_verdict(engine, text, rows, check)
    return verdict, stated, computed, check


def _invalid(engine: Engine, rows: list[RowResult], entries: list[Entry]) -> list[str]:
    """Entries whose code the engine cannot read (after the rows before it)."""
    out = []
    for e in entries:
        i = e.row
        check = engine.check("\n".join(r.code for r in rows[:i + 1] if r.code))
        if check.error is not None and check.error.kind == "invalid":
            out.append(f"Row {i}: the engine rejects the code `{rows[i].code}`: {check.error.message}")
    return out


_ENGINE_PREFIX = re.compile(r"^(Round|Row)\s+\d+:\s*")


def _was_faithful(before: RowResult, after: RowResult) -> bool:
    return bool(before.faithful and before.code and before.code != after.code)


def _judge_rows(engine: Engine, text: str, original: list[RowResult], rows: list[RowResult], entries: list[Entry],
                cache_dir: Path) -> tuple[dict[int, RowResult], dict[int, str], float]:
    """The faithfulness checker over every changed row. Returns (judged rows, {row: why it failed}, cost).

    `original` are the pipeline's rows, `rows` the assembled ones. A fix is judged against its fixed text.
    """
    judged, reasons, total, guide = {}, {}, 0.0, engine.notation_guide()
    for e in entries:
        row = rows[e.row]
        if e.verdict != "fix" and _keeps(e):
            continue
        english = _english(engine, rows, e.row)
        if all(line.startswith("UNSUPPORTED") for line in english):
            reasons[e.row] = (f"Row {e.row}: the code can't be put into words, so it couldn't be compared with the text")
            continue
        context, shown = "", text
        if e.verdict == "fix":
            context = _FIX_CONTEXT.format(explanation=e.explanation or "a mistake in the text")
            old = original[e.row].source
            shown = text.replace(old, e.fixed_text) if old in text else text
        elif e.verdict == "reading":
            context = _READING_CONTEXT.format(explanation=e.explanation or "another reading")
        answer, cost = _judge(guide, shown, row, english, cache_dir, context)
        total += cost
        what = "fixed text" if e.verdict == "fix" else "written row"
        if answer["verdict"] == "faithful" and e.verdict != "fix" and _was_faithful(original[e.row], row):
            # the old code was already confirmed as the row's plain reading, so different code is another reading
            plain = " ".join(_ENGINE_PREFIX.sub("", line) for line in english).strip().rstrip(". ")
            answer = {"verdict": "interpreted", "reading": plain,
                      "reason": e.explanation or "the words can be read another way"}
        if answer["verdict"] in ("faithful", "interpreted"):
            judged[e.row] = _with_answer(row, english, answer)
        elif answer["verdict"] == "mismatch":
            reasons[e.row] = (f"Row {e.row}: the checker says your code does not match the {what}: "
                           f"{answer['reason'] or 'it differs from the words'}")
        else:
            reasons[e.row] = (f"Row {e.row}: the checker could not tell if your code matches the {what}"
                           + (f" ({answer['reason']})" if answer["reason"] else ""))
    return judged, reasons, total


def evaluate(engine: Engine, text: str, rows: list[RowResult], who: str, reply: dict,
             faithful_cache_dir: Path = FAITHFUL_CACHE_DIR) -> Story:
    """Run the referee over one side's reply (the model reply dict with a "text"). Rows are the pipeline's."""
    story = Story(who, cost=reply.get("cost_usd") or 0.0)
    got = read_reply(reply.get("text", ""))
    if isinstance(got, str):
        story.reasons.append(got)
        return story
    story.summary = got[0]
    kept, story.reasons = vet(who, rows, got[1])
    story.kept = kept
    if who == "bob" and not any(e.verdict == "fix" for e in kept):
        story.reasons.append("no valid fix was given (a fix needs a quote from the row and a changed fixed_text)")
        return story
    if not kept:
        story.reasons.append("your answer changes nothing")
        return story
    assembled = _assemble(rows, kept)
    invalid = _invalid(engine, assembled, kept)
    if invalid:
        story.reasons += invalid
        return story
    verdict, _, _, _ = _passes(engine, text, assembled)
    if verdict.kind not in PASSING:
        story.reasons.append(f"with your answer the engine check finds: {verdict.message}"
                             + (f" (at row {verdict.row})" if verdict.row is not None else ""))
        return story
    judged, failed, cost = _judge_rows(engine, text, rows, assembled, kept, faithful_cache_dir)
    story.cost += cost
    if failed:  # a change the checker rejects is dropped; the story stands only if it passes without it
        kept = [e for e in kept if e.row not in failed]
        story.reasons += list(failed.values())
        if not kept or (who == "bob" and not any(e.verdict == "fix" for e in kept)):
            return story
        verdict, _, _, _ = _passes(engine, text, _assemble(rows, kept, judged))
        if verdict.kind not in PASSING:
            story.reasons.append(f"without the rejected rows the engine check finds: {verdict.message}")
            return story
        story.reasons = []
    kept = _prune(engine, text, rows, kept, judged) if who == "bob" else kept
    final = _assemble(rows, kept, judged)
    story.rows = final
    story.kept = kept
    story.fixes = [e for e in kept if e.verdict == "fix"]
    story.verdict, story.stated, story.computed, story.check = _passes(engine, text, final)
    story.passed = story.verdict.kind in PASSING
    if not story.passed:
        story.reasons.append(f"with your answer the engine check finds: {story.verdict.message}")
    return story


def _prune(engine: Engine, text: str, rows: list[RowResult], kept: list[Entry], judged: dict) -> list[Entry]:
    """Drop the fixes that the story passes without (last first), so the smallest set is shown."""
    kept = list(kept)
    for e in reversed([e for e in kept if e.verdict == "fix"]):
        if sum(x.verdict == "fix" for x in kept) <= 1:
            break
        trial = [x for x in kept if x is not e]
        verdict, _, _, _ = _passes(engine, text, _assemble(rows, trial, judged))
        if verdict.kind in PASSING:
            kept = trial
    return kept


# ---- asking ----
def _finding(report: PatternReport) -> str:
    v = report.verdict
    return f"{v.kind}: {v.message}" if v else "nothing yet"


def _listing(rows: list[RowResult]) -> str:
    """The rows as the translator prompts show them, plus the reading an earlier check already settled on."""
    out = []
    for r in rows:
        shown = _rows_listing([r])
        if r.reading and r.faithful:
            shown += f"\n    (already read as: {r.reading})"
        out.append(shown)
    return "\n".join(out)


def _prompt(guide: str, text: str, report: PatternReport, who: str, reasons: list[str]) -> str:
    feedback = ""
    if reasons:
        feedback = ("\nYour previous answer was checked by a program and rejected:\n"
                    + "\n".join(f"- {r}" for r in reasons)
                    + "\nGive a complete new answer that avoids these problems.\n")
    return PROMPT.read_text(encoding="utf-8").format(
        guide=guide, task=TASKS[who].read_text(encoding="utf-8").strip(), original=text.strip(),
        rows=_listing(report.rows), finding=_finding(report), feedback=feedback)


def _ask(guide: str, text: str, report: PatternReport, who: str, reasons: list[str], cache_dir: Path) -> dict:
    reply, cost = ask_cached(_prompt(guide, text, report, who, reasons), ROLE, ANSWER_SCHEMA, cache_dir, "review")
    return {"text": reply["text"], "cost_usd": cost}


def _numbers(engine: Engine, story: Story) -> dict[int, int]:
    """Position in the story's rows -> the pattern's row number."""
    mapped, _ = _map_rows(engine, story.rows, story.check)
    written = [p for p, r in enumerate(story.rows) if not r.synthetic]
    return {p: m.number for p, m in zip(written, mapped)}


def _fixes(engine: Engine, story: Story, original: list[RowResult]) -> list[Fix]:
    number = _numbers(engine, story)
    fixes = [Fix(number.get(e.row, e.row), original[e.row].source, e.fixed_text, e.explanation) for e in story.fixes]
    return sorted(fixes, key=lambda f: f.row)


def review_report(engine: Engine, text: str, report: PatternReport, *, cache_dir: Path = CACHE_DIR,
                  faithful_cache_dir: Path = FAITHFUL_CACHE_DIR, max_attempts: int = MAX_ATTEMPTS) -> float:
    """Ask Alice and Bob about a pattern that did not simply work, and update the report. Returns the cost.

    Needs the model; does nothing for a pattern that works or whose break was counted by the ledger.
    """
    if not needs_review(report):
        return 0.0
    from .messages import user_message  # late: messages reads the report this function changes

    rows, guide, total = report.rows, engine.notation_guide(), 0.0
    observed = user_message(report)
    obs_verdict = report.verdict
    reasons = {"alice": [], "bob": []}
    alice = bob = None
    attempts = 0
    for attempts in range(1, max_attempts + 1):
        alice = evaluate(engine, text, rows, "alice", _ask(guide, text, report, "alice", reasons["alice"], cache_dir),
                         faithful_cache_dir)
        total += alice.cost
        if alice.literal:
            bob = None
            break
        bob = evaluate(engine, text, rows, "bob", _ask(guide, text, report, "bob", reasons["bob"], cache_dir),
                       faithful_cache_dir)
        total += bob.cost
        if alice.passed or bob.passed:
            break
        reasons = {"alice": alice.reasons, "bob": bob.reasons}

    passed = alice.passed or bool(bob and bob.passed)
    review = Review("none", attempts, alice.summary, bob.summary if bob else "", alice.passed,
                    bool(bob and bob.passed), [] if passed else alice.reasons + (bob.reasons if bob else []))
    report.review = review
    if alice.literal:  # the pattern works as written; the first reading of it was just wrong
        review.outcome = "works"
        _take(report, alice)
    elif alice.passed and bob and bob.passed:
        review.outcome = "ambiguous"
        fixes = _fixes(engine, bob, rows)
        _take(report, alice)
        v = report.verdict
        message = "it works under the readings above, but read literally a row is wrong"
        report.verdict = Verdict("ambiguous", message, row=fixes[0].row, interpreted=v.interpreted, fixes=fixes,
                                 observed=observed, observed_row=obs_verdict.row)
        review.fixed_report = _fixed_report(text, bob)
    elif alice.passed:
        review.outcome = "works_with_readings"
        _take(report, alice)
    elif bob and bob.passed:
        review.outcome = "fix"
        fixes = _fixes(engine, bob, rows)
        report.verdict = Verdict("breaks", fixes[0].explanation, row=fixes[0].row, fixes=fixes, observed=observed,
                                 observed_row=obs_verdict.row, reading=obs_verdict.reading if obs_verdict else "")
        review.fixed_report = _fixed_report(text, bob)
    return total


def _take(report: PatternReport, story: Story) -> None:
    """Make the story's pattern the report's: its rows, check, verdict and counts."""
    report.rows, report.check, report.verdict = story.rows, story.check, story.verdict
    report.stated, report.computed = story.stated, story.computed


def _fixed_report(text: str, story: Story) -> PatternReport:
    return PatternReport(text=text, rows=story.rows, check=story.check, verdict=story.verdict,
                         stated=story.stated, computed=story.computed)
