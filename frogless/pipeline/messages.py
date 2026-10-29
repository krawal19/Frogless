"""The sentence(s) a crocheter reads: user_message(report) turns a PatternReport into plain words."""

import re
from difflib import SequenceMatcher

from .report import Fix, PatternReport, Verdict
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


def _slide(words: list[str], i1: int, i2: int) -> list[str]:
    """The removed words, moved to the equivalent spot that starts and ends at a sentence or phrase boundary
    ("a. b. b. c" lost one "b.": say 'b.', not '. b' ...)."""
    stop = (".", ",", ";", ":")
    kept = words[:i1] + words[i2:]

    def score(i: int) -> int:
        return (i == 0 or words[i - 1].endswith(stop)) + words[i + (i2 - i1) - 1].endswith(stop)

    starts = [i for i in range(len(words) - (i2 - i1) + 1) if words[:i] + words[i + (i2 - i1):] == kept]
    best = max(starts, key=lambda i: (score(i), i == i1))
    return words[best:best + (i2 - i1)]


def change_text(original: str, fixed: str) -> str:
    """What a fix does to a row, in a few words: 'remove ...', 'change ... to ...', 'add ... after ...'."""
    a, b = _quote(original).split(), _quote(fixed).split()
    ops = [o for o in SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if o[0] != "equal"]
    if not ops or len(ops) > 3:
        return f"make it read '{_quote(fixed)}'"
    parts = []
    for tag, i1, i2, j1, j2 in ops:
        old, new = " ".join(a[i1:i2]), " ".join(b[j1:j2])
        if tag == "delete":
            parts.append(f"remove '{' '.join(_slide(a, i1, i2))}'")
        elif tag == "replace":
            parts.append(f"change '{old}' to '{new}'")
        else:
            before = " ".join(a[max(0, i1 - 3):i1])
            parts.append(f"add '{new}' after '{before}'" if before else f"add '{new}' at the start")
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + ", and " + parts[-1]


def _labelled(f: Fix, word: str) -> str:
    """An inserted row as it would be written, with its label."""
    text = f.fixed_text.strip()
    return text if _LABEL.match(text) else f"{word} {f.row}: {text}"


def _fix_phrase(f: Fix, word: str) -> str:
    if f.insert:
        return f"insert '{_labelled(f, word)}'"
    return f"in {word} {f.row}, {change_text(f.original, f.fixed_text)}"


def _fix_changes(v: Verdict, word: str) -> str:
    return "; ".join(_fix_phrase(f, word) for f in v.fixes if not f.conditional)


def _conditional_note(f: Fix, word: str) -> str:
    """A row that is right if the turning chain counts as a stitch, with the fix if it does not."""
    unit = "" if f.said is None or f.made is None else (
        "one" if abs(f.said - f.made) == 1 else str(abs(f.said - f.made)))
    off = "" if not unit else f"it is {unit} {'short' if f.made < f.said else 'over'}"
    return (f"{word} {f.row} works if the turning chain counts as a stitch; if not, {off or 'it breaks'} "
            f"(fix: {change_text(f.original, f.fixed_text)})")


def _conditional_notes(v: Verdict, word: str) -> str:
    notes = [_conditional_note(f, word) for f in v.fixes if f.conditional]
    return "⚠ " + "; ".join(notes) + "." if notes else ""


def _with_fixes(report: PatternReport, v: Verdict, word: str) -> str:
    """A pattern that breaks, with the fixes that were re-checked and make it work (and the conditional notes)."""
    real = [f for f in v.fixes if not f.conditional]
    first = real[0]
    if first.insert:
        head = f"❌ Breaks at {word} {v.row}: a {word.lower()} seems to be missing before it."
    elif v.observed.startswith("❌") and v.observed_row == v.row:
        head = v.observed.rstrip()
    else:
        head = f"❌ Breaks at {word} {v.row}: {v.message.rstrip('.')}."
        conditional_rows = {f.row for f in v.fixes if f.conditional}
        if v.observed_row is not None and v.observed_row != v.row and v.observed_row not in conditional_rows:
            head += f" The counts first fail at {word} {v.observed_row}."
    many = len(real) > 1
    lone_insert = len(real) == 1 and first.insert
    text = (f"{head} Suggested{'' if lone_insert else ' fixes' if many else ' fix'}: {_fix_changes(v, word)} "
            f"(re-checked: the pattern works with {'these fixes' if many else 'it' if lone_insert else 'this fix'}).")
    notes = _conditional_notes(v, word)
    return f"{text} {notes}" if notes else text


def fix_lines(report: PatternReport) -> list[str]:
    """The suggested fixes, for the person who wrote the pattern: what to change, why, and how the row then reads."""
    v, word = report.verdict, _word(report)
    if v is None or not v.fixes:
        return []
    lines = []
    for f in v.fixes:
        why = f" ({f.explanation.rstrip('.')})" if f.explanation else ""
        if f.insert:
            lines.append(f"Suggested fix: insert a new {word.lower()} as {word} {f.row}{why}")
            lines.append(f"  {word} {f.row} would read: {_quote(f.fixed_text)}")
            continue
        only = " (only if the turning chain does not count as a stitch)" if f.conditional else ""
        lines.append(f"Suggested fix, {word} {f.row}{only}: {change_text(f.original, f.fixed_text)}{why}")
        lines.append(f"  {word} {f.row} would read: {_quote(f.fixed_text)}")
    lines.append("Re-checked: the pattern works with " + ("these fixes." if len(v.fixes) > 1 else "this fix."))
    return lines


TURN_NOTE = "Works only if the turning chain counts as a stitch."
CHAINS_NOTE = "The counts only work if the chains are left out."


def _notes(v: Verdict) -> list[str]:
    """The conventions a passing pattern leans on that the pattern itself never states."""
    notes = [TURN_NOTE] if v.reading == TURN_COUNTS else []
    return notes + ([CHAINS_NOTE] if v.chains_left_out else [])


def _ambiguous(v: Verdict, word: str) -> str:
    if v.fixes and all(f.conditional for f in v.fixes):
        return _conditional_notes(v, word)
    if v.fixes:
        rows = [f.row for f in v.fixes]
        return ("⚠ Works if " + ", and if ".join(_interpretations(v, word))
                + f"; read literally, {_rows(word, rows)} {'is' if len(set(rows)) == 1 else 'are'} wrong"
                + f" (fix: {_fix_changes(v, word)}).")
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
        text = f"✅ Stitch counts check out, but {which} couldn't be double-checked."
        clauses = _interpretations(v, word)
        if clauses:
            text += " They also assume " + ", and ".join(clauses) + "."
        return text + (f" ⚠ {notes}" if notes else "")
    if v.kind == "works_counts_only":
        which = _rows(word, v.counted)
        text = (f"✅ Stitch counts check out. {which} {'was' if len(set(v.counted)) == 1 else 'were'} "
                "checked by count only (they can't be drawn stitch by stitch).")
        if v.rows:
            text += f" {_rows(word, v.rows)} couldn't be double-checked."
        clauses = _interpretations(v, word)
        if clauses:
            text += " They also assume " + ", and ".join(clauses) + "."
        return text + (f" ⚠ {notes}" if notes else "")
    if v.kind == "ambiguous":
        return _ambiguous(v, word)
    if v.kind == "breaks" and v.fixes:
        return _with_fixes(report, v, word)
    if v.kind == "breaks":
        by_ai = ""
        said, made = report.stated.get(v.row), report.computed.get(v.row)
        if said is not None and made is not None and said != made:
            text = f"❌ Breaks at {word} {v.row}: the pattern says {said}, but the instructions make {made}{by_ai}."
            if v.reading == TURN_COUNTS:
                text = text[:-1] + " (counting the turning chain as a stitch)."
            return text
        detail = re.sub(r"^(rows?|rounds?)\s+\d+:\s*", "", v.message, flags=re.IGNORECASE).rstrip(".")
        return f"❌ Breaks at {word} {v.row}: {detail}{by_ai}."
    return _unreadable(report, v, word)


def shape_lines(report: PatternReport) -> list[str]:
    """Shape hints for the person following the pattern, one line each. Kept apart from
    user_message so the verdict line stays clean; the hints never change the verdict."""
    return [f"{'⚠' if f.severity == 'warning' else 'ℹ'} {f.message}" for f in report.shape]
