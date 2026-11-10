"""Code -> English: turn engine code back into literal US-crochet sentences.

One sentence per code line (blank lines and # comments are skipped). The wording is
literal, not prettified: the faithfulness check compares it with the original pattern,
and the same wording is what the rules translator reads back in for the plain constructs
(see tests/test_describe.py for the round trip).

Covered: plain, increase, decrease, loop-only, post, bobble/popcorn/puff, reverse sc and
picot stitches; chains, skips, turns, foundation rows; magic-ring rounds; labels (.A) and
attachments (@A, @R0, @[@], @1L); groups worked into one place; the partial-repeat marker.

Anything this module cannot describe comes back as "UNSUPPORTED: <raw code>" instead of
a guess.

Reused from the translator package: canonicalize_cp (whitespace and "[..]*n" ->
"n*[..]" normalization). The translator only goes English -> code, so the code parser
and the English templates below are the parts written here.
"""

import re
from dataclasses import dataclass, field, replace

from .oval import label_foundation

BASE_STITCHES = {"sc", "hdc", "dc", "tr", "dtr", "trtr"}
_WORDS = {"ch", "sk", "turn", "ring", "tie_up"}
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_STITCH_RE = re.compile(
    r"(?P<post>fp|bp)?(?P<base>trtr|dtr|tr|hdc|dc|sc|ss|rsc)(?P<loop>bl|fl)?"
    r"(?:(?P<k>\d+)(?P<kind>inc|tog))?"
)
_SPECIAL_RE = re.compile(r"(?:(?P<base>hdc|dc|tr)(?P<k>\d+)(?P<kind>bobble|pc|puff)|picot(?P<pk>\d+))")
_LABEL_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?")
_HEAD_RE = re.compile(r"(\d+)([A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?)")
_KIND_NAMES = {"bobble": "bobble", "pc": "popcorn", "puff": "puff"}


class _Unsupported(Exception):
    pass


@dataclass
class Atom:
    name: str  # base stitch or word: sc, ch, ss, sk, turn, ring, picot ...
    n: int = 1  # how many in a row
    kind: str = ""  # "", "inc", "tog", "bobble", "pc" or "puff"
    k: int = 0  # stitches in the inc/tog/bobble, chains in the picot
    labels: list[str] = field(default_factory=list)  # .A
    attach: str = ""  # raw text after @
    post: str = ""  # "fp" or "bp"
    loop: str = ""  # "bl" or "fl"


@dataclass
class Group:
    items: list  # Atom | Group | Marker
    times: int = 1
    repeated: bool = False  # written as n*[...]
    labels: list[str] = field(default_factory=list)
    attach: str = ""


@dataclass
class Marker:
    kind: str  # ">" last repeat stops here, "<" first repeat starts here


@dataclass
class _Ctx:
    reg: dict  # label -> (kind, size), kind is "st", "space" or "group"
    bare: bool = False  # inside a group worked into one place: no "in next st"
    unit: str = "st"  # "ch" on the row worked along a foundation chain
    chain_label: str = ""  # label on the first chain of the foundation chain: a group worked into it is the way back


# ---------------------------------------------------------------- parsing
def _make_atom(token, n):
    if token in _WORDS:
        return Atom(token, n)
    m = _SPECIAL_RE.fullmatch(token)
    if m:
        if m.group("pk"):
            if int(m.group("pk")) < 1:
                raise _Unsupported("picot")
            return Atom("picot", n, k=int(m.group("pk")))
        if int(m.group("k")) < 2:
            raise _Unsupported("bobble size")
        return Atom(m.group("base"), n, kind=m.group("kind"), k=int(m.group("k")))
    m = _STITCH_RE.fullmatch(token)
    if not m:
        raise _Unsupported(f"stitch {token}")
    post, base, loop = m.group("post") or "", m.group("base"), m.group("loop") or ""
    kind, k = m.group("kind") or "", int(m.group("k") or 0)
    if post and (loop or base not in BASE_STITCHES):
        raise _Unsupported("post stitch")
    if kind and (base not in BASE_STITCHES or k < 2):
        raise _Unsupported("inc/tog")
    return Atom(base, n, kind=kind, k=k, post=post, loop=loop)


class _Parser:
    def __init__(self, text):
        self.s = text
        self.i = 0

    def peek(self):
        return self.s[self.i] if self.i < len(self.s) else ""

    def number(self):
        m = re.compile(r"\d+").match(self.s, self.i)
        if not m:
            return None
        self.i = m.end()
        return int(m.group())

    def sequence(self, close=""):
        items = []
        while True:
            items.append(self.item())
            c = self.peek()
            if c == ",":
                self.i += 1
                continue
            if c == close:
                if close:
                    self.i += 1
                return items
            raise _Unsupported(f"unexpected {c!r}")

    def item(self):
        start = self.i
        n = self.number()
        if self.peek() == "*":  # n*[...] or n*(...)
            self.i += 1
            if n is None or self.peek() not in ("(", "["):
                raise _Unsupported("repeat")
            g = self.group()
            g.times, g.repeated = n, True
            return g
        if self.peek() in ("(", "["):
            if n is not None:
                raise _Unsupported("count before group")
            return self.group()
        if self.peek() in ("<", ">"):
            if n is not None:
                raise _Unsupported("count before marker")
            c = self.peek()
            self.i += 1
            return Marker(c)
        m = _TOKEN_RE.match(self.s, self.i)
        if not m:
            raise _Unsupported(f"stitch at {start}")
        self.i = m.end()
        atom = _make_atom(m.group(), 1 if n is None else n)
        atom.labels, atom.attach = self.modifiers()
        return atom

    def group(self):
        close = ")" if self.peek() == "(" else "]"
        self.i += 1
        g = Group(items=self.sequence(close))
        g.labels, g.attach = self.modifiers()
        return g

    def modifiers(self):
        labels, attach = [], ""
        while self.peek() in (".", "@"):
            c = self.peek()
            self.i += 1
            if c == ".":
                m = _LABEL_RE.match(self.s, self.i)
                if not m:
                    raise _Unsupported("label")
                labels.append(m.group())
                self.i = m.end()
            else:
                attach = self.attach_text()
        return labels, attach

    def attach_text(self):
        if self.peek() == "[":
            depth, j = 0, self.i
            while j < len(self.s):
                depth += {"[": 1, "]": -1}.get(self.s[j], 0)
                j += 1
                if depth == 0:
                    break
            if depth:
                raise _Unsupported("unbalanced attachment")
            text, self.i = self.s[self.i : j], j
            return text
        m = _HEAD_RE.match(self.s, self.i) or _LABEL_RE.match(self.s, self.i)
        if not m:
            raise _Unsupported("attachment")
        self.i = m.end()
        return m.group()


def _parse_line(line):
    p = _Parser(line)
    items = p.sequence()
    if p.i != len(line):
        raise _Unsupported("trailing text")
    return items


def _register(items, reg):
    """Remember what each label marks (a stitch, a chain space or a group)."""
    for it in items:
        if isinstance(it, Atom):
            for lab in it.labels:
                reg[lab] = ("space" if it.name == "ch" else "st", it.n)
        elif isinstance(it, Group):
            _register(it.items, reg)
            for lab in it.labels:
                reg[lab] = ("group", 1)


# ---------------------------------------------------------------- English
def _sts(n, unit="st"):
    if unit == "ch":
        return "next ch" if n == 1 else f"next {n} ch"
    return "next st" if n == 1 else f"next {n} sts"


def _place(attach, ctx, n=1):
    """Where an attachment points: (text, each). each=True means one stitch per marked st."""
    if attach == "R0":
        return "magic ring", False
    if attach == "[@]":
        return "the same st", False
    if attach == "sp":
        return "the next chain space of the row below", False
    head = _HEAD_RE.fullmatch(attach)
    if head:
        if head.group(1) != "1":
            raise _Unsupported("attachment head")
        kind = ctx.reg.get(head.group(2), ("?", 1))[0]
        what = {"space": "space", "st": "st"}.get(kind, "st/space")
        return f"marked {what} {head.group(2)} (second attachment head, worked back along it)", False
    if _LABEL_RE.fullmatch(attach):
        kind, size = ctx.reg.get(attach, ("?", 1))
        if kind == "space":
            return f"marked space {attach}", False
        if kind == "st":
            if size == 1:
                return f"marked st {attach}", False
            if n == size:
                return f"the {size} marked sts {attach}", True
            raise _Unsupported("attachment to a stitch group")
        return f"marked st/space {attach}", False
    raise _Unsupported("attachment")


def _noun(a):
    word = {"rsc": "reverse sc"}.get(a.name, a.name)
    return {"fp": "front post ", "bp": "back post "}.get(a.post, "") + word


def _mark_what(a):
    if a.name == "ch":
        return "this space"
    if not a.kind and a.n > 1:
        return f"these {a.n} sts"
    return "this st"


def _atom_text(a: Atom, ctx):
    text = _atom_core(a, ctx)
    if a.labels:
        text += f" (mark {_mark_what(a)} as {' and '.join(a.labels)})"
    return text


def _atom_core(a: Atom, ctx):
    name, n, k = a.name, a.n, a.k
    if name == "turn":
        if n != 1 or a.attach or a.labels or ctx.bare:
            raise _Unsupported("turn")
        return "turn"
    if name == "sk":
        if a.attach == "sp" and n == 1 and not a.labels and not ctx.bare:
            return "skip next chain space"
        if a.attach or a.labels or ctx.bare:
            raise _Unsupported("skip")
        if ctx.unit == "ch":
            return "skip next ch" if n == 1 else f"skip next {n} ch"
        return "skip next st" if n == 1 else f"skip {n}"
    if name == "ch":
        if a.attach:
            raise _Unsupported("attachment")
        return f"ch {n}"
    if name in ("ring", "tie_up"):
        raise _Unsupported(f"stitch {name}")
    if name == "picot":
        if a.attach or (ctx.bare and n != 1):
            raise _Unsupported("picot")
        one = f"{k}-ch picot (ch {k}, ss back into the st before it)"
        return one if n == 1 else f"({one}) {n} times"

    if name == "ss" and a.attach == "[%,0]" and n == 1 and not a.kind and not a.loop and not ctx.bare:
        return "ss to first st"
    place, each = None, False
    if a.attach:
        if ctx.bare:
            raise _Unsupported("attachment inside a group")
        place, each = _place(a.attach, ctx, n)

    noun = _noun(a)
    loopof = {"bl": "back loop only of ", "fl": "front loop only of "}.get(a.loop, "")
    loop_par = {"bl": " (back loop only)", "fl": " (front loop only)"}.get(a.loop, "")
    conn = "around" if a.post else "in"
    if place and name == "ss" and place.startswith(("marked", "the marked")):
        conn = "to"
    cnt = f"{n} " if n > 1 else ""

    if a.kind == "":
        if place is None and not ctx.bare:
            return f"{noun} {conn} {loopof}{_sts(n, ctx.unit)}"
        if ctx.bare:
            return f"{cnt}{noun}{loop_par}"
        if each:
            return f"{noun} {conn} {loopof}each of {place}"
        return f"{cnt}{noun} {conn} {loopof}{place}"

    if a.kind == "inc":
        if name not in BASE_STITCHES or k < 2:
            raise _Unsupported("inc")
        if place is None and not ctx.bare:
            if n == 1:
                return f"{k} {noun} {conn} {loopof}{_sts(1, ctx.unit)}"
            return f"{k} {noun} {conn} {loopof}each of {_sts(n, ctx.unit)}"
        if n != 1 or each:
            raise _Unsupported("inc")
        return f"{k} {noun}{loop_par}" if ctx.bare else f"{k} {noun} {conn} {loopof}{place}"

    if a.kind == "tog":
        if name not in BASE_STITCHES or k < 2 or place is not None:
            raise _Unsupported("tog")
        loops = {"bl": " in back loops only", "fl": " in front loops only"}.get(a.loop, "")
        one = f"{_noun(replace(a, name=f'{name}{k}tog'))}{loops}"
        if ctx.bare:
            if n != 1:
                raise _Unsupported("tog")
            return one
        return one if n == 1 else f"({one}) {n} times"

    if a.kind in _KIND_NAMES:
        noun_b = f"{k}-{name} {_KIND_NAMES[a.kind]}"
        if ctx.bare:
            return noun_b if n == 1 else f"{n} {noun_b}s"
        if place is None:
            return f"{noun_b} in next st" if n == 1 else f"{noun_b} in each of next {n} sts"
        if n != 1 or each:
            raise _Unsupported("bobble")
        return f"{noun_b} in {place}"
    raise _Unsupported("stitch")


def _items_text(items, ctx):
    return ", ".join(_item_text(i, ctx) for i in items)


def _item_text(item, ctx):
    if isinstance(item, Atom):
        return _atom_text(item, ctx)
    if isinstance(item, Marker):
        raise _Unsupported("marker outside a repeat")
    return _group_text(item, ctx)


def _is_plain(a):
    return isinstance(a, Atom) and not a.kind and not a.attach and not a.labels and not a.post and not a.loop


def _group_text(g: Group, ctx):
    if g.attach:
        if g.repeated:
            raise _Unsupported("repeated group attachment")
        return _placed_group_text(g, ctx)
    if g.labels and g.repeated:
        raise _Unsupported("repeated group label")
    text = _plain_group_text(g, ctx)
    if g.labels:
        text += f" (mark all of these as {' and '.join(g.labels)})"
    return text


def _plain_group_text(g: Group, ctx):
    markers = [i for i in g.items if isinstance(i, Marker)]
    if markers and not g.repeated:
        raise _Unsupported("marker outside a repeat")
    only = g.items[0] if len(g.items) == 1 else None
    if g.repeated and _is_plain(only) and only.name in BASE_STITCHES | {"ch", "ss"}:  # 3*[sc] is just 3sc
        return _atom_text(Atom(only.name, only.n * g.times), ctx)
    inner = ", ".join("[marker]" if isinstance(i, Marker) else _item_text(i, ctx) for i in g.items)
    if not g.repeated:
        return f"({inner})"
    text = f"({inner}) {g.times} time{'' if g.times == 1 else 's'}"
    for m in markers:
        text += (
            "; on the last repeat stop at the marker"
            if m.kind == ">"
            else "; on the first repeat start at the marker"
        )
    return text


def _placed_group_text(g: Group, ctx):
    """(...)@place: every stitch in the group goes into that one place."""
    if ctx.bare:
        raise _Unsupported("nested placed group")
    if ctx.chain_label and g.attach == ctx.chain_label and not g.labels:
        back = replace(ctx, chain_label="")  # the other side of the foundation chain, stitch by stitch
        return f"rotate, then work along the other side of the foundation chain ({_items_text(g.items, back)})"
    only = g.items[0] if len(g.items) == 1 else None
    if _is_plain(only) and only.name not in _WORDS:
        text = _atom_text(replace(only, attach=g.attach), ctx)  # (6sc)@R0 -> 6 sc in magic ring
    else:
        place, each = _place(g.attach, ctx)
        if each:
            raise _Unsupported("group into stitch group")
        inner = ", ".join(_item_text(i, replace(ctx, bare=True)) for i in g.items)
        text = f"({inner}) all in {place}"
    if g.labels:
        text += f" (mark all of these as {' and '.join(g.labels)})"
    return text


def _canon(code):
    """Whitespace/postfix-repeat normalization, reused from the translator package."""
    from .. import get_engine
    from .adapter import _add_python_path

    _add_python_path(get_engine().repo)  # the clone's python/ dir
    from crochetparade_translator.dsl.canonicalize import canonicalize_cp

    return canonicalize_cp(code)


def _is_atom(items, name):
    return len(items) == 1 and isinstance(items[0], Atom) and items[0].name == name and not items[0].kind


def _uses_ring(items):
    return any(
        (isinstance(i, Group) and i.attach == "R0") or (isinstance(i, Atom) and i.attach == "R0") for i in items
    )


def _has_turn(items):
    return any(
        (isinstance(i, Atom) and i.name == "turn") or (isinstance(i, Group) and _has_turn(i.items)) for i in items
    )


def describe_code(code: str) -> list[str]:
    """One English sentence per code line; 'UNSUPPORTED: <code>' for what we can't say."""
    lines = [l for l in label_foundation(_canon(code)).splitlines() if l.strip() and not l.lstrip().startswith("#")]
    parsed = []
    for raw in lines:
        try:
            parsed.append((raw, _parse_line(raw)))
        except _Unsupported:
            parsed.append((raw, None))

    # Rows (turned, built on a foundation chain) versus rounds (worked around).
    first = parsed[0][1] if parsed else None
    chains, chain_label = _foundation(first) if len(parsed) > 1 else (0, "")
    foundation = chains > 0
    rows_mode = foundation or any(items and _has_turn(items) for _, items in parsed)
    if any(items and _uses_ring(items) for _, items in parsed):
        rows_mode = False
    word = "Row" if rows_mode else "Round"

    out, number, reg = [], 0, {}
    for idx, (raw, items) in enumerate(parsed):
        unsupported = f"UNSUPPORTED: {raw}"
        if items is None:
            number += 1
            out.append(unsupported)
            continue
        _register(items, reg)
        try:
            if _is_atom(items, "ring") and items[0].attach == "" and items[0].labels == ["R0"] and items[0].n == 1:
                out.append("Make a magic ring.")
                continue
            if _is_atom(items, "tie_up") and not items[0].labels and not items[0].attach:
                out.append("Fasten off.")
                continue
            if _is_atom(items, "turn") and not items[0].labels and not items[0].attach and items[0].n == 1:
                out.append("Turn.")  # a bare turn line is not a row of its own
                continue
            if idx == 0 and foundation:
                out.append(f"Ch {chains}.")
                continue
            ctx = _Ctx(reg)
            if idx == 1 and foundation:
                body = _foundation_row_text(chains, items, replace(ctx, unit="ch", chain_label=chain_label))
            else:
                body = _round_text(items, ctx) if word == "Round" else _items_text(items, ctx)
            number += 1
            out.append(f"{word} {number}: {body}.")
        except _Unsupported:
            number += 1
            out.append(unsupported)
    return out


def _foundation(items) -> tuple[int, str]:
    """(chains, label) of a line that is a foundation chain, (0, "") if it is not. The label is the one on its first
    chain (`ch.A,12ch` is 13 chains), where an oval's way back along the other side is attached."""
    if items is None:
        return 0, ""
    if _is_atom(items, "ch") and not items[0].labels and not items[0].attach:
        return items[0].n, ""
    if (len(items) == 2 and all(_is_atom([i], "ch") and not i.attach for i in items) and len(items[0].labels) == 1
            and items[0].n == 1 and not items[1].labels):
        return 1 + items[1].n, items[0].labels[0]
    return 0, ""


def _round_text(items, ctx):
    """A round's text; a plain ss ending the round is the join, not another stitch."""
    last = items[-1]
    if len(items) > 1 and _is_plain(last) and last.name == "ss" and last.n == 1:
        return ", ".join([_items_text(items[:-1], ctx), "join with sl st to first st"])
    return _items_text(items, ctx)


_FROM_HOOK = {"sc": "2nd", "hdc": "3rd", "dc": "4th"}
# Skips before the first stitch that are said as "stitch in the Nth ch from hook": the skipped chains are
# the turning chain (hdc skips 2, dc skips 3). One fewer skip (hdc 1, dc 2: the turning chain counted as that
# stitch) is a different row, one stitch longer, so it is said as a plain skip and the reader can see the difference.
_HOOK_SKIPS = {"sc": (0, 1), "hdc": (2,), "dc": (3,)}


def _foundation_row_text(chains, items, ctx):
    """Row 1 worked along a foundation chain, e.g. 'sk,10sc,turn' on Ch 11."""
    rest, skipped = list(items), 0
    if rest and isinstance(rest[0], Atom) and rest[0].name == "sk" and _is_plain(rest[0]):
        skipped, rest = rest[0].n, rest[1:]
    if rest and _is_plain(rest[0]) and rest[0].name in _FROM_HOOK:
        s = rest[0]
        tail_ok = all(
            isinstance(i, Atom) and i.name in ("ch", "turn") and not i.attach and not i.labels for i in rest[1:]
        )
        # the stitches worked are the chains left after the skipped ones (sc: after the 1st)
        worked = chains - (1 if s.name == "sc" else skipped)
        if tail_ok and skipped in _HOOK_SKIPS[s.name] and s.n == worked:
            head = f"{s.name} in {_FROM_HOOK[s.name]} ch from hook and in each ch across"
            tail = _items_text(rest[1:], replace(ctx, unit="st"))
            return head + (f", {tail}" if tail else "")
    return _items_text(items, ctx)
