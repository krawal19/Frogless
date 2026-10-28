"""The sentence(s) a crocheter reads: user_message(report) turns a PatternReport into plain words."""

import re

from .report import PatternReport, Verdict
from .verdict import TURN_COUNTS

_LABEL = re.compile(r"^\s*(?P<word>rows?|rounds?|rnds?|r)\b\s*[\d\s\-–,&and]*:\s*", re.IGNORECASE)


def _word(report: PatternReport) -> str:
    """'Row' or 'Round', as the pattern calls its rows."""
    for r in report.rows:
        m = None if r.synthetic else _LABEL.match(r.source)
        if m:
            return "Row" if m["word"].lower().startswith("row") else "Round"
    return "Round"


def _numbers(numbers: list[int]) -> str:
    """[2, 3, 4, 7] -> '2-4, 7'; runs of one or two are listed."""
    nums, out, i = sorted(set(numbers)), [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out += [f"{nums[i]}-{nums[j]}"] if j - i >= 2 else [str(n) for n in nums[i:j + 1]]
        i = j + 1
    return ", ".join(out)


def _rows(word: str, numbers: list[int]) -> str:
    return f"{word}{'s' if len(set(numbers)) > 1 else ''} {_numbers(numbers)}"


def _quote(source: str) -> str:
    return _LABEL.sub("", source.strip(), count=1).strip().rstrip(".")


def _interpretations(v: Verdict, word: str) -> list[str]:
    """One clause per interpreted row (rows of one written range share a clause)."""
    groups: dict[tuple[str, str, str], list[int]] = {}
    for it in v.interpreted:
        groups.setdefault((it.source, it.reading, it.why), []).append(it.row)
    clauses = []
    for (source, reading, why), numbers in groups.items():
        quote = f"'{_quote(source)}'"
        subject = f"{_rows(word, numbers)}'s {quote}" if len(numbers) == 1 else f"{quote} in {_rows(word, numbers)}"
        clauses.append(f"{subject} means {reading}" + (f" ({why})" if why else ""))
    return clauses


def _short(word: str, row: int, said: int | None, made: int | None) -> str:
    if said is None or made is None or said == made:
        return f"{word} {row} breaks"
    n = abs(said - made)
    unit = "one stitch" if n == 1 else f"{n} stitches"
    return f"{word} {row} is {unit} {'short' if made < said else 'over'}"


TURN_NOTE = "Works only if the turning chain counts as a stitch."
CHAINS_NOTE = "The counts only work if the chain spaces are counted."


def _notes(v: Verdict) -> list[str]:
    """The conventions a passing pattern leans on that the pattern itself never states."""
    notes = [TURN_NOTE] if v.reading == TURN_COUNTS else []
    return notes + ([CHAINS_NOTE] if v.chains_counted else [])


def _ambiguous(v: Verdict, word: str) -> str:
    def result(alt):
        return "works" if alt.row is None else _short(word, alt.row, alt.said, alt.made)

    counted = next((a for a in v.alternatives if a.reading == TURN_COUNTS), None)
    other = next((a for a in v.alternatives if a is not counted), None)
    if not counted or not other:
        return f"⚠ {v.message}."
    return ("⚠ Depends on how you count turning chains. "
            f"If the turning chain counts as a stitch: {result(counted)}. If not: {result(other)}.")


def _unreadable(report: PatternReport, v: Verdict, word: str) -> str:
    if v.row is None:
        return f"❓ We couldn't read this pattern ({v.message})."
    row = next((r for r in report.rows if not r.synthetic and not r.code and r.status != "ok"), None) or \
        next((r for r in report.rows if not r.synthetic and not r.code), None)
    reason = (row.note if row and row.note else "the instructions weren't recognized").rstrip(".")
    text = f"❓ We couldn't read {word} {v.row} ({reason})."
    if any(n < v.row for n in report.computed) and not v.rows:  # earlier rows counted and none unconfirmed
        text += " Everything before it checks out."
    return text


def user_message(report: PatternReport) -> str:
    """What to tell the person who wrote (or is following) the pattern."""
    v, word = report.verdict, _word(report)
    if v is None:
        return ""
    notes = " ".join(_notes(v))
    if v.kind == "works":
        clauses = _interpretations(v, word)
        if clauses:
            text = "✅ Works, if " + ", and if ".join(clauses) + "."
            return text + (f" ⚠ {notes}" if notes else "")
        if notes:
            return f"⚠ {notes}"
        return "✅ This pattern works. Every row's stitch count checks out."
    if v.kind == "works_unverified":
        which = _rows(word, v.rows)
        verb = "was" if len(set(v.rows)) == 1 else "were"
        text = f"✅ Stitch counts check out, but {which} {verb} read by AI and couldn't be double-checked."
        clauses = _interpretations(v, word)
        if clauses:
            text += " They also assume " + ", and ".join(clauses) + "."
        return text + (f" ⚠ {notes}" if notes else "")
    if v.kind == "ambiguous":
        return _ambiguous(v, word)
    if v.kind == "breaks":
        said, made = report.stated.get(v.row), report.computed.get(v.row)
        if said is not None and made is not None and said != made:
            text = f"❌ Breaks at {word} {v.row}: the pattern says {said}, but the instructions make {made}."
            if v.reading == TURN_COUNTS:
                text = text[:-1] + " (counting the turning chain as a stitch)."
            return text
        detail = re.sub(r"^(rows?|rounds?)\s+\d+:\s*", "", v.message, flags=re.IGNORECASE).rstrip(".")
        return f"❌ Breaks at {word} {v.row}: {detail}."
    return _unreadable(report, v, word)
