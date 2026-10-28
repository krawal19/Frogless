"""What check_pattern() returns. Engine-neutral: no engine syntax beyond the code strings."""

from dataclasses import dataclass, field

from ..engine import CheckResult


@dataclass
class RowResult:
    index: int  # position among the translated rows (0-based)
    source: str  # the row's text as the translator saw it
    code: str = ""  # final engine code for this row ("" if none)
    origin: str = "rules"  # "rules" (rules translator), "model" (language model), "none"
    status: str = "ok"  # "ok", "flagged" (no code yet), "cannot" (model said it can't)
    synthetic: bool = False  # added by the translator, not written in the pattern
    note: str = ""  # why it was flagged, or the model's CANNOT reason
    english: str = ""  # the code turned back into English (faithfulness check)
    faithful: bool | None = None  # None = not checked (or the checker could not tell)
    reading: str = ""  # faithfulness check: the one reading the code picked for an ambiguous row ("" if none)
    why: str = ""  # faithfulness check: what is unclear in the written row (with `reading`)


@dataclass
class Interpreted:
    """A row whose wording is ambiguous; the code picked one sensible reading of it."""

    row: int  # the pattern's row/round number
    source: str  # the row as written
    reading: str  # what the code does
    why: str  # what is unclear in the written row


@dataclass
class Alternative:
    """One way of counting and what it gives, for an "ambiguous" verdict."""

    reading: str  # the counting convention
    row: int | None  # where the pattern breaks under it, None if it works
    said: int | None = None  # stated count there, if a stated count is what failed
    made: int | None = None  # count the instructions make there


@dataclass
class Verdict:
    kind: str  # "works", "works_unverified", "breaks", "ambiguous", "unreadable"
    message: str
    row: int | None = None  # the pattern's row/round number where it breaks
    readings: list[str] = field(default_factory=list)  # for "ambiguous": the readings that fit
    alternatives: list[Alternative] = field(default_factory=list)  # for "ambiguous": each reading's outcome
    reading: str = ""  # TURN_COUNTS when only that reading fit the stated counts (a fallback); "" otherwise
    chains_counted: bool = False  # some bare count fits only with the chain spaces counted (a fallback)
    interpreted: list[Interpreted] = field(default_factory=list)  # rows the code had to read one way
    rows: list[int] = field(default_factory=list)  # for "works_unverified": rows the model wrote and nothing confirmed


@dataclass
class PatternReport:
    text: str
    rows: list[RowResult]
    check: CheckResult | None = None  # engine result on the assembled code
    verdict: Verdict | None = None
    stated: dict[int, int] = field(default_factory=dict)  # row number -> count the pattern states
    computed: dict[int, int] = field(default_factory=dict)  # row number -> count the engine makes
    cost_usd: float = 0.0  # model spend for this check
    notes: list[str] = field(default_factory=list)  # anything else worth telling the user
    shape: list = field(default_factory=list)  # ShapeFinding hints about the finished piece; never change the verdict

    @property
    def code(self) -> str:
        return "\n".join(r.code for r in self.rows if r.code)
