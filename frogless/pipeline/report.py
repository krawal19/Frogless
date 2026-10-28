"""What check_pattern() returns. Engine-neutral: no engine syntax beyond the code strings."""

from dataclasses import dataclass, field

from ..engine import CheckResult
from ..patterns.terms import Terms


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
    # Stitch ledger (rows the engine cannot model; the model reads the counts, our code does the arithmetic):
    ledger_uses: int | None = None  # stitches of the row below this row works into (incl. ones it skips)
    ledger_makes: int | None = None  # stitches this row makes
    ledger_ok: bool | None = None  # None: not a ledger row; True: counts fit; False: they do not
    ledger_note: str = ""  # what did not fit (ledger_ok False), or how the counts came out


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
class Fix:
    """A suggested change to the written pattern that was re-checked and makes the whole pattern work."""

    row: int  # the pattern's row/round number
    original: str  # the row as written
    fixed_text: str  # the whole row as it would read after the fix
    explanation: str  # what is wrong with the written row


@dataclass
class Review:
    """What the Alice-and-Bob review did (it runs when a pattern does not simply work)."""

    outcome: str  # "works", "works_with_readings", "ambiguous", "fix", "none"
    attempts: int = 0  # rounds of asking (1-3)
    alice: str = ""  # Alice's story ("the pattern is right as written"), one line for display
    bob: str = ""  # Bob's story ("the pattern has a mistake"), one line for display
    alice_passed: bool = False
    bob_passed: bool = False
    reasons: list[str] = field(default_factory=list)  # why a story was rejected, last attempt
    fixed_report: "PatternReport | None" = None  # the pattern with Bob's fixes applied (outcome "fix", "ambiguous")


@dataclass
class Verdict:
    kind: str  # "works", "works_unverified", "works_counts_only", "breaks", "ambiguous", "unreadable"
    message: str
    row: int | None = None  # the pattern's row/round number where it breaks
    readings: list[str] = field(default_factory=list)  # for "ambiguous": the readings that fit
    alternatives: list[Alternative] = field(default_factory=list)  # for "ambiguous": each reading's outcome
    reading: str = ""  # TURN_COUNTS when only that reading fit the stated counts (a fallback); "" otherwise
    chains_counted: bool = False  # some bare count fits only with the chain spaces counted (a fallback)
    interpreted: list[Interpreted] = field(default_factory=list)  # rows the code had to read one way
    rows: list[int] = field(default_factory=list)  # for "works_unverified": rows the model wrote and nothing confirmed
    counted: list[int] = field(default_factory=list)  # for "works_counts_only": rows read by AI and checked by count only
    ledger: bool = False  # for "breaks": the row was counted by AI, not modelled
    fixes: list[Fix] = field(default_factory=list)  # suggested fixes that were re-checked and work
    observed: str = ""  # with fixes: what the check found before the review (the original message)
    observed_row: int | None = None  # with fixes: the row the check found it at


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
    terms: Terms | None = None  # US or UK stitch names, as detected or chosen
    review: Review | None = None  # the Alice-and-Bob review, if it ran

    @property
    def code(self) -> str:
        return "\n".join(r.code for r in self.rows if r.code)
