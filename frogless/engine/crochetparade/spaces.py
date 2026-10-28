"""Naming chain spaces, so a row can say "into the next chain space" (`dc@sp`).

The model writes `@sp` on a stitch (or `(group)@sp`) that goes into the next unworked chain space of
the row below, in working order: left to right after a round, right to left after a turned row.
Real labels (`ch.A`, then `@A`) need a name for every space and a repeat written out, which the
model cannot do reliably for a 45-space mesh row. So this step does it: it writes out the repeats
of the two rows involved, gives every chain space of the row below a generated name (or keeps the
label the model gave it), and replaces each `@sp` with the name of the space it reaches.

A chain space is a run of chains with a real stitch on both sides; turning chains at the start or
end of a row and the foundation chain are not spaces. Back-to-back chains are one space.
"""

import re
from dataclasses import dataclass, field


class SpaceError(ValueError):
    """An `@sp` that cannot be resolved (no row below, or more `@sp` than the row below has spaces)."""


SP = re.compile(r"@sp\b")
CHAIN = re.compile(r"^\d*ch((?:\.\w+)*)$")
REPEAT_HEAD = re.compile(r"^\d+\*$")


@dataclass
class Leaf:
    text: str


@dataclass
class Group:
    items: list
    suffix: str = ""  # what follows the closing bracket: "@A", ".B"


@dataclass
class Repeat:
    count: int
    items: list = field(default_factory=list)


# ---- parsing ----
class _Reader:
    def __init__(self, text):
        self.s, self.i = text, 0

    def peek(self):
        return self.s[self.i] if self.i < len(self.s) else ""

    def sequence(self, close):
        items = []
        while True:
            items.append(self.item(close))
            c = self.peek()
            if c == ",":
                self.i += 1
            elif c == close:
                if close:
                    self.i += 1
                return items
            else:
                raise SpaceError("could not read the row")

    def item(self, close):
        if self.peek() == "(":
            self.i += 1
            group = Group(self.sequence(")"))
            group.suffix = self.leaf_text(close)
            return group
        text = ""
        while True:
            c = self.peek()
            if c in ("", ",") or c == close:
                return Leaf(text)
            if c == "[" and REPEAT_HEAD.match(text):
                self.i += 1
                rep = Repeat(int(text[:-1]), self.sequence("]"))
                if self.peek() not in ("", ",", close):
                    raise SpaceError("could not read the row")
                return rep
            if c == "[":  # an attachment such as @[@]
                end = self.s.find("]", self.i)
                if end < 0:
                    raise SpaceError("could not read the row")
                text += self.s[self.i:end + 1]
                self.i = end + 1
                continue
            text += c
            self.i += 1

    def leaf_text(self, close):
        text = ""
        while self.peek() not in ("", ",", close):
            text += self.peek()
            self.i += 1
        return text


def _parse(line):
    reader = _Reader(line)
    items = reader.sequence("")
    if reader.i != len(line):
        raise SpaceError("could not read the row")
    return items


def _expand(items):
    """The same items with every repeat written out (each copy is its own object)."""
    out = []
    for it in items:
        if isinstance(it, Repeat):
            if any(isinstance(x, Leaf) and x.text == ">" for x in _leaves(it.items)):
                raise SpaceError("a repeat that ends part way cannot be written out")
            for _ in range(it.count):
                out.extend(_expand(it.items))
        elif isinstance(it, Group):
            out.append(Group(_expand(it.items), it.suffix))
        else:
            out.append(Leaf(it.text))
    return out


def _leaves(items):
    for it in items:
        if isinstance(it, Group):
            yield from _leaves(it.items)
        elif isinstance(it, Repeat):
            yield from _leaves(it.items)
        else:
            yield it


def _text(items):
    parts = []
    for it in items:
        if isinstance(it, Group):
            parts.append("(" + _text(it.items) + ")" + it.suffix)
        else:
            parts.append(it.text)
    return ",".join(parts)


# ---- naming ----
def _name_spaces(items, row, taken):
    """Give each chain space a name (keeping labels already there). Returns the names, in code order."""
    leaves = list(_leaves(items))
    stitch = [k for k, lf in enumerate(leaves) if not CHAIN.match(lf.text) and lf.text != "turn"]
    if not stitch:
        return []
    first, last = stitch[0], stitch[-1]
    runs = []  # [label, [leaf indexes]]
    for k, lf in enumerate(leaves):
        m = CHAIN.match(lf.text)
        if not m:
            runs.append(None)
            continue
        label = m.group(1).split(".")[1] if m.group(1) else ""
        cur = runs[-1] if runs and runs[-1] is not None else None
        if cur and not (label and cur[0] and label != cur[0]):
            cur[0] = cur[0] or label
            cur[1].append(k)
        else:
            cur = [label, [k]]
        runs.append(cur)
    names, seen = [], set()
    n = 0
    for run in runs:
        if run is None or id(run) in seen:
            continue
        seen.add(id(run))
        label, idx = run
        if not (first < idx[0] and idx[-1] < last):
            continue
        if not label:
            while True:
                n += 1
                label = f"sp{row}n{n}"
                if label not in taken:
                    break
            taken.add(label)
            leaves[idx[0]].text += "." + label
        names.append(label)
    return names


def _labels(code):
    return set(re.findall(r"\.(\w+)", code))


def resolve_spaces(code: str) -> str:
    """Replace each `@sp` by the name of the chain space it reaches. Code without `@sp` is returned as is."""
    if not SP.search(code):
        return code
    lines = code.split("\n")
    rows = [i for i, line in enumerate(lines) if line.strip()]
    taken = _labels(code) | {"R0"}
    for pos, i in enumerate(rows):
        if not SP.search(lines[i]):
            continue
        if pos == 0:
            raise SpaceError("a stitch is worked into a chain space but there is no row below it")
        j = rows[pos - 1]
        below = _expand(_parse(lines[j].strip()))
        names = _name_spaces(below, j, taken)
        lines[j] = _text(below)
        ends_turned = bool(below) and isinstance(below[-1], Leaf) and below[-1].text == "turn"
        if ends_turned:
            names.reverse()
        row = _text(_expand(_parse(lines[i].strip())))
        wanted = len(SP.findall(row))
        if wanted > len(names):
            raise SpaceError(
                f"a row works into {wanted} chain spaces of the row below, which has {len(names)}")
        it = iter(names)
        lines[i] = SP.sub(lambda _m: "@" + next(it), row)
    return "\n".join(lines)
