"""Read the shape of a pasted pattern before it is translated: pieces, one round per line, labels, prose.

Engine-neutral plain text to plain text, no model calls (like repeats.py and wording.py). The pre-pass:

- splits a paste with several pieces ("BODY + HEAD - Yarn A", "ARMS x2", "Face plate:", or a label that restarts at 1
  after a higher label) into one text per piece, so each piece is checked on its own and its rows count from 1;
- puts every round on a line of its own ("R1 6 sc in MR [6] R2 inc x6 [12]");
- gives a colon to a label without one ("R1 6 sc in MR" -> "R1: 6 sc in MR");
- reads a bare count ("R4-5 [12]") as "sc around" only when the count equals the round before (the usual
  amigurumi convention) and says so; any other bare count is left as written, no stitches are invented;
- keeps prose (no stitch word, no label: "stuff, pull closed", "Fasten off leaving a long tail") as notes, never glued
  onto a round, and splits prose off the end of a round line ("[6] - stuff, pull closed").

Nothing is dropped: every non-blank input line ends up as a row, a header or a note (Piece.segments).
"""

import re
from dataclasses import dataclass, field

from .stated import stated_count

_LABEL = re.compile(r"^\s*(?P<word>rows?|rnds?|rounds?|r)\.?\s*(?P<a>\d+)(?:\s*[-–]\s*(?P<b>\d+))?(?!\d)", re.IGNORECASE)
_LABEL_COLON = r"(?:rows?|rnds?|rounds?|r)\.?\s*\d+(?:\s*[-–]\s*\d+)?\s*:"
# the words that make a text an instruction rather than prose
_INSTR = re.compile(
    r"\b(?:sc|dc|hdc|tr|dtr|trc|ch|chs|inc|dec|sk|skip|sl\s*st|slst|ss|turn|join|mr|ring|sc2tog|dc2tog|hdc2tog|"
    r"rep|repeat|yo|blo|flo|bl|fl|sp|space|beg|rnd|rnds|round|rounds|row|rows)\b|\d+\s*times|[x×]\s*\d+", re.IGNORECASE)
_COUNT = re.compile(r"[\[(]\s*\d+\s*(?:sts?|stitch(?:es)?|sc|dc|hdc|tr|ch)?\s*[\])](?!\s*[x×*]|\s*\d+\s*times)", re.IGNORECASE)
_SEP = re.compile(r"^\s*(?P<sep>[—–]|-(?=\s)|[.;])?\s*")
_COLON_SPLIT = re.compile(rf"(?<=[.;\])])\s+(?={_LABEL_COLON})", re.IGNORECASE)
_BARE = re.compile(r"^(?P<count>[\[(]\s*(?P<n>\d+)\s*(?:sts?|stitch(?:es)?)?\s*[\])])\s*\.?$", re.IGNORECASE)
_KEEP_AS_IS = re.compile(r"^\s*(?:[:.)\-–—]|\((?:rs|ws)\))", re.IGNORECASE)  # punctuation already follows the label
_HEADER_BAD = re.compile(r"[.!?,]\s*$|,")
_SENTENCE_END = re.compile(r"[.!?,]\s*$")
_BARE_STITCH = re.compile(r"^(?:sc|hdc|dc|tr)\s*(?P<count>[\[(]\s*(?P<n>\d+)\s*(?:sts?|stitch(?:es)?)?\s*[\])])\s*\.?$", re.IGNORECASE)
_MAKE = re.compile(r"\(?\s*(?:make\s+)?[x×]\s*\d+\s*\)?|\(\s*make\s+\d+\s*\)|\bmake\s+\d+", re.IGNORECASE)
_PROSE_START = re.compile(r"^(?:fasten|fo|stuff|sew|weave|embroider|attach|add|finish|cut|pull|bind|eyes?|note|materials|abbreviations)\b", re.IGNORECASE)

BARE_READING = "read '{label} {count}' as {stitch} around (the round before also has {n} stitches)"
BARE_SAME_AS = "read '{label} {count}' as {label} of '{where}': {body}"
BARE_UNREAD = "'{label} {count}' states only a count, no stitches; left as written (nothing was invented)"


@dataclass
class Segment:
    source: str  # the input line this text came from
    kind: str  # "row", "header" or "note"
    text: str  # what it became


@dataclass
class Piece:
    label: str  # the piece's header, "Piece N" when it has none
    text: str  # the piece as the checker reads it
    notes: list[str] = field(default_factory=list)  # prose kept as notes, in order
    readings: list[str] = field(default_factory=list)  # what the pre-pass interpreted, to tell the user
    segments: list[Segment] = field(default_factory=list)  # every input line, as a row, header or note


def _label_numbers(text: str) -> tuple[int, int] | None:
    m = _LABEL.match(text)
    return (int(m["a"]), int(m["b"] or m["a"])) if m else None


def _split_round_line(line: str) -> list[tuple[str, str]]:
    """A labelled line as [("row", text), ...] with further rounds and trailing prose (("note", text)) split off."""
    out: list[tuple[str, str]] = []
    rest = line.strip()
    while rest:
        for m in _COUNT.finditer(rest):
            sep = _SEP.match(rest[m.end():])
            tail = rest[m.end() + sep.end():]
            if not tail:
                continue
            if _LABEL.match(tail):
                out.append(("row", rest[:m.end()]))
                rest = tail
                break
            if sep["sep"] and not _INSTR.search(tail):
                out += [("row", rest[:m.end()]), ("note", tail)]
                rest = ""
                break
        else:
            out.append(("row", rest))
            rest = ""
    rows: list[tuple[str, str]] = []
    for kind, text in out:  # "R1: 6 sc. R2: inc x6": a colon label after a full stop starts a round too
        rows += [(kind, p) for p in (_COLON_SPLIT.split(text) if kind == "row" else [text])]
    return rows


def _with_colon(row: str) -> tuple[str, str, str]:
    """(label, body, row) with a colon after the label if it has none."""
    m = _LABEL.match(row)
    label, body = row[:m.end()].strip(), row[m.end():]
    if body.lstrip().startswith(":"):
        return label, body.lstrip()[1:].strip(), f"{label}: {body.lstrip()[1:].strip()}".strip()
    if not body.strip() or _KEEP_AS_IS.match(body):
        return label, body.strip(), row.strip()
    return label, body.strip(), f"{label}: {body.strip()}"


def _header_like(text: str) -> bool:
    """A short line that names a piece: "ARMS x2 - Yarn A", "Face plate:", "FEET (make 2)", "Arms"."""
    if len(text) > 70 or len(text.split()) > 8 or _PROSE_START.match(text):
        return False
    bare = _MAKE.sub("", text)
    if _INSTR.search(bare) or (_SENTENCE_END.search(bare) and not bare.rstrip().endswith(":")):
        return False
    letters = [c for c in bare if c.isalpha()]
    caps = bool(letters) and all(c.isupper() for c in letters)
    named = caps or " — " in text or " + " in text or text.rstrip().endswith(":")
    if "," in bare and not named and not re.match(r"^[A-Z]{2,}", text):
        return False
    return caps or re.match(r"^[A-Z]{2,}", text) is not None or text.endswith(":") or bare != text or " — " in text or " + " in text or len(text.split()) <= 3


def _classify(line: str) -> list[tuple[str, str]]:
    """The line as [(kind, text)]: row (a labelled round), instr (an unlabelled instruction), note (prose),
    cand (prose short enough to be a piece header) or blank."""
    if not line.strip():
        return [("blank", "")]
    if _LABEL.match(line):
        return _split_round_line(line)
    text = line.strip()
    if _header_like(text):
        return [("cand", text)]
    if not _INSTR.search(text):
        return [("note", text)]
    return [("instr" if kind == "row" else kind, t) for kind, t in _split_round_line(text)]


class _Builder:
    def __init__(self):
        self.pieces: list[Piece] = []
        self.piece: Piece | None = None
        self.entries: list[tuple[str, Segment | None]] = []  # the current piece's text lines (None: a blank line)
        self.last_end = 0  # the last round number the current piece has reached
        self.prev_count: int | None = None
        self.pending: list[Segment] = []  # prose before the first piece's first line
        self.firsts: dict[int, tuple[Piece, str]] = {}  # N -> (piece, its "R1" row) for each written R1 stating N

    @property
    def has_work(self) -> bool:
        return any(seg is not None for _, seg in self.entries)

    def start(self, label: str = "", carry: list[tuple[str, Segment | None]] = ()) -> Piece:
        self.finish()
        self.piece = Piece(label=label, text="")
        self.entries, self.last_end, self.prev_count = list(carry), 0, None
        self.piece.segments += [seg for _, seg in carry if seg]
        if not self.pieces and self.pending:  # prose before the first piece belongs to it
            self.piece.segments[:0] = self.pending
            self.piece.notes += [s.text for s in self.pending]
            self.pending = []
        return self.piece

    def finish(self) -> None:
        if self.piece is not None:
            while self.entries and not self.entries[-1][0].strip():
                self.entries.pop()
            self.piece.text = "\n".join(text for text, _ in self.entries)
            self.pieces.append(self.piece)
            self.piece = None

    def ensure(self) -> Piece:
        return self.piece or self.start()

    def header(self, source: str, text: str, label: str) -> None:
        self.piece.label = label
        self.piece.segments.append(Segment(source, "header", text))

    def note(self, source: str, text: str) -> None:
        seg = Segment(source, "note", text)
        if self.piece is None and not self.pieces:
            self.pending.append(seg)
            return
        piece = self.ensure()
        piece.notes.append(text)
        piece.segments.append(seg)

    def blank(self) -> None:
        if self.piece and self.has_work:
            self.entries.append(("", None))

    def restart(self) -> None:
        """A label restarts: a new piece. Instructions without a label after the last round (a foundation chain
        written before the new piece's first round) go with the new piece."""
        carry = []
        while self.entries and (not self.entries[-1][0].strip() or not _LABEL.match(self.entries[-1][0])):
            carry.insert(0, self.entries.pop())
        for _, seg in carry:
            if seg:
                self.piece.segments.remove(seg)
        self.start("", carry)

    def row(self, source: str, text: str) -> None:
        piece = self.ensure()
        if _LABEL.match(text):
            label, body, text = _with_colon(text)
            bare = _BARE.match(body)
            stitch = _BARE_STITCH.match(body)
            numbers = _label_numbers(text)
            if bare:
                n = int(bare["n"])
                earlier = self.firsts.get(n)
                if self.prev_count == n:
                    text = f"{label}: sc around {bare['count']}"
                    piece.readings.append(BARE_READING.format(label=label, count=bare["count"], n=n, stitch="sc"))
                elif self.prev_count is None and numbers == (1, 1) and earlier and earlier[0] is not piece:
                    where, written = earlier
                    text = f"{label}: {written}"
                    piece.readings.append(BARE_SAME_AS.format(label=label, count=bare["count"], where=where.label,
                                                              body=written))
                else:
                    piece.readings.append(BARE_UNREAD.format(label=label, count=bare["count"]))
            elif stitch and self.prev_count == int(stitch["n"]):  # "R10-18 sc [54]" after a round of 54
                name = re.match(r"[a-z]+", body, re.IGNORECASE).group(0).lower()
                text = f"{label}: {name} around {stitch['count']}"
                piece.readings.append(BARE_READING.format(label=label, count=body, n=stitch["n"], stitch=name))
            elif numbers == (1, 1) and body.strip():
                stated = stated_count(text)
                if stated and not stated.multi_size:
                    self.firsts.setdefault(stated.count, (piece, body.strip()))
            numbers = _label_numbers(text)
            self.last_end = numbers[1] if numbers else self.last_end
            stated = stated_count(text)
            self.prev_count = stated.count if stated and not stated.multi_size else None
        else:  # an instruction without a label ("Ch 13.")
            self.prev_count = None
        seg = Segment(source, "row", text)
        piece.segments.append(seg)
        self.entries.append((text, seg))


def split_pieces(text: str) -> list[Piece]:
    """The pattern as one Piece per piece. A pattern of one piece gives one Piece."""
    items: list[tuple[str, str, str]] = []  # (source line, kind, text)
    for line in text.split("\n"):
        items += [(line.strip(), kind, t) for kind, t in _classify(line)]

    def next_work(i: int) -> str | None:
        for _, kind, _ in items[i + 1:]:
            if kind != "blank":
                return kind
        return None

    def next_label(i: int) -> tuple[int, int] | None:
        for _, kind, t in items[i + 1:]:
            if kind == "cand":
                return None
            if kind == "row":
                return _label_numbers(t)
        return None

    b = _Builder()
    for i, (source, kind, t) in enumerate(items):
        if kind == "blank":
            b.blank()
        elif kind == "cand":
            starts = next_work(i) in ("row", "instr")
            nxt = next_label(i)
            name = t.rstrip(":").strip()
            if starts and not b.has_work and not (b.piece and b.piece.label):  # the first piece's header
                b.ensure()
                b.header(source, t, name)
            elif starts and b.has_work and nxt and b.last_end and nxt[0] <= b.last_end:  # the next round restarts
                b.start(name)
                b.header(source, t, name)
            else:
                b.note(source, t)
        elif kind == "note":
            b.note(source, t)
        else:
            numbers = _label_numbers(t) if kind == "row" else None
            if numbers and b.has_work and b.last_end and numbers[0] <= b.last_end:  # a label restarts
                b.restart()
            b.row(source, t)
    if b.piece is None and not b.pieces:  # nothing but prose
        b.start()
    b.finish()
    for n, piece in enumerate(b.pieces, 1):
        piece.label = piece.label or f"Piece {n}"
    return b.pieces
