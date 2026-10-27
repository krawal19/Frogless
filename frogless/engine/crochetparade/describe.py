"""Code -> English: turn engine code back into literal US-crochet sentences.

One sentence per code line (blank lines and # comments are skipped). The wording is
literal, not prettified: the faithfulness check compares it with the original pattern,
and the same wording is what the rules translator reads back in (see
tests/test_describe.py for the round trip).

Anything this module cannot describe comes back as "UNSUPPORTED: <raw code>" instead of
a guess.

Reused from the translator package: canonicalize_cp (whitespace and "[..]*n" ->
"n*[..]" normalization). The translator only goes English -> code, so the code parser
and the English templates below are the parts written here.
"""

import re
from dataclasses import dataclass, field

BASE_STITCHES = {"sc", "hdc", "dc", "tr", "dtr", "trtr"}
_NAME_RE = re.compile(r"(?P<name>[A-Za-z_]+?)(?:(?P<k>\d+)(?P<kind>inc|tog))?(?![A-Za-z0-9_])")
_LABEL_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?")


class _Unsupported(Exception):
    pass


@dataclass
class Atom:
    name: str  # base stitch or word: sc, ch, ss, sk, turn, tie_up, ring ...
    n: int = 1  # how many in a row
    kind: str = ""  # "", "inc" or "tog"
    k: int = 0  # stitches in the inc/tog
    labels: list[str] = field(default_factory=list)  # .A
    attach: str = ""  # raw text after @


@dataclass
class Group:
    items: list  # Atom | Group
    times: int = 1
    repeated: bool = False  # written as n*[...]
    labels: list[str] = field(default_factory=list)
    attach: str = ""


# ---------------------------------------------------------------- parsing
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
            if n is None or self.peek() not in "([":
                raise _Unsupported("repeat")
            g = self.group()
            g.times, g.repeated = n, True
            return g
        if self.peek() in ("(", "["):
            if n is not None:
                raise _Unsupported("count before group")
            return self.group()
        m = _NAME_RE.match(self.s, self.i)
        if not m or not m.group("name"):
            raise _Unsupported(f"stitch at {start}")
        self.i = m.end()
        atom = Atom(
            name=m.group("name"),
            n=1 if n is None else n,
            kind=m.group("kind") or "",
            k=int(m.group("k") or 0),
        )
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
        m = _LABEL_RE.match(self.s, self.i)
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


# ---------------------------------------------------------------- English
def _sts(n):
    return "next st" if n == 1 else f"next {n} sts"


def _atom_text(a: Atom):
    if a.labels:
        base = _atom_text(Atom(a.name, a.n, a.kind, a.k, [], a.attach))
        return f"{base} (mark as {', '.join(a.labels)})"
    if a.attach:
        if a.name == "ss" and a.attach == "[%,0]" and a.n == 1 and not a.kind:
            return "ss to first st"
        if re.fullmatch(_LABEL_RE, a.attach) and a.attach != "R0" and a.n == 1 and not a.kind:
            if a.name in BASE_STITCHES or a.name == "ss":
                return f"{a.name} in marked st {a.attach}"
        raise _Unsupported("attachment")
    name, n = a.name, a.n
    if a.kind == "inc":
        if a.name not in BASE_STITCHES or a.k < 2:
            raise _Unsupported("inc")
        if n == 1:
            return f"{a.k} {name} in next st"
        return f"{a.k} {name} in each of next {n} sts"
    if a.kind == "tog":
        if a.name not in BASE_STITCHES or a.k < 2:
            raise _Unsupported("tog")
        word = f"{name}{a.k}tog"
        return word if n == 1 else f"({word}) {n} times"
    if name in BASE_STITCHES:
        return f"{name} in {_sts(n)}"
    if name == "ch":
        return f"ch {n}"
    if name == "ss":
        return f"ss in {_sts(n)}"
    if name == "sk":
        return "skip next st" if n == 1 else f"skip {n}"
    if name == "turn" and n == 1:
        return "turn"
    raise _Unsupported(f"stitch {name}")


def _items_text(items):
    return ", ".join(_item_text(i) for i in items)


def _item_text(item):
    if isinstance(item, Atom):
        return _atom_text(item)
    if item.attach or item.labels:
        raise _Unsupported("group attachment")
    only = item.items[0] if len(item.items) == 1 else None
    if item.repeated and isinstance(only, Atom) and not only.kind and not only.attach and not only.labels:
        if only.name in BASE_STITCHES | {"ch", "ss"}:  # 3*[sc] is just 3sc
            return _atom_text(Atom(only.name, only.n * item.times))
    inner = _items_text(item.items)
    if item.repeated:
        return f"({inner}) {item.times} time{'' if item.times == 1 else 's'}"
    return f"({inner})"


def _ring_text(items):
    """(Nsc)@R0 -> 'N sc in magic ring' (optionally after a chain such as ch 2)."""
    parts = []
    for it in items:
        if isinstance(it, Group) and it.attach == "R0":
            if it.labels or it.repeated or len(it.items) != 1:
                raise _Unsupported("ring group")
            a = it.items[0]
            if not (isinstance(a, Atom) and a.name in BASE_STITCHES and not a.kind and not a.attach and not a.labels):
                raise _Unsupported("ring group")
            parts.append(f"{a.n} {a.name} in magic ring")
        else:
            parts.append(_item_text(it))
    return ", ".join(parts)


def _is_atom(items, name):
    return len(items) == 1 and isinstance(items[0], Atom) and items[0].name == name and not items[0].kind


def _uses_ring(items):
    return any(isinstance(i, Group) and i.attach == "R0" for i in items)


def _canon(code):
    """Whitespace/postfix-repeat normalization, reused from the translator package."""
    from .. import get_engine
    from .adapter import _add_python_path

    _add_python_path(get_engine().repo)  # the clone's python/ dir
    from crochetparade_translator.dsl.canonicalize import canonicalize_cp

    return canonicalize_cp(code)


def describe_code(code: str) -> list[str]:
    """One English sentence per code line; 'UNSUPPORTED: <code>' for what we can't say."""
    lines = [l for l in _canon(code).splitlines() if l.strip() and not l.lstrip().startswith("#")]
    parsed = []
    for raw in lines:
        try:
            parsed.append((raw, _parse_line(raw)))
        except _Unsupported:
            parsed.append((raw, None))

    # Rows (turned, built on a foundation chain) versus rounds (worked around).
    def has_turn(items):
        return any(
            (isinstance(i, Atom) and i.name == "turn") or (isinstance(i, Group) and has_turn(i.items))
            for i in items
        )

    foundation = bool(parsed) and parsed[0][1] is not None and _is_atom(parsed[0][1], "ch") and len(parsed) > 1
    rows_mode = foundation or any(items and has_turn(items) for _, items in parsed)
    if any(items and _uses_ring(items) for _, items in parsed):
        rows_mode = False
    word = "Row" if rows_mode else "Round"

    out, number = [], 0
    for idx, (raw, items) in enumerate(parsed):
        unsupported = f"UNSUPPORTED: {raw}"
        if items is None:
            number += 1
            out.append(unsupported)
            continue
        try:
            if _is_atom(items, "ring") and items[0].attach == "" and items[0].labels == ["R0"] and items[0].n == 1:
                out.append("Make a magic ring.")
                continue
            if _is_atom(items, "tie_up"):
                out.append("Fasten off.")
                continue
            if idx == 0 and foundation:
                out.append(f"Ch {items[0].n}.")
                continue
            number += 1
            body = _ring_text(items) if _uses_ring(items) else _items_text(items)
            if idx == 1 and foundation and _is_foundation_row(parsed[0][1][0].n, items):
                body = _foundation_row_text(items)
            out.append(f"{word} {number}: {body}.")
        except _Unsupported:
            out.append(unsupported)
    return out


_FROM_HOOK = {"sc": "2nd", "hdc": "3rd", "dc": "4th"}


def _is_foundation_row(chains, items):
    """Row 1 worked once along a foundation chain: Nsc [,turn] with N = chains - 1."""
    first = items[0]
    return (
        isinstance(first, Atom)
        and first.name == "sc"
        and not first.kind
        and not first.attach
        and not first.labels
        and first.n == chains - 1
        and all(isinstance(i, Atom) and i.name == "turn" for i in items[1:])
        and len(items) <= 2
    )


def _foundation_row_text(items):
    text = f"{items[0].name} in {_FROM_HOOK[items[0].name]} ch from hook and in each ch across"
    return text + (", turn" if len(items) == 2 else "")
