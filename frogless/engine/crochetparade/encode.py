"""Spec -> engine code. The only place that knows the engine's syntax for generated patterns."""

from frogless.testset.spec import Item, Repeat, skipped

TURNING_CHAIN = {"sc": "ch", "hdc": "2ch", "dc": "3ch"}


def encode(spec) -> str:
    lines = []
    if spec.start == "ring":
        lines.append("ring.R0")
    else:
        lines.append(f"{spec.chain}ch")
    last = len(spec.rows) - 1
    for i, row in enumerate(spec.rows):
        body = ",".join(_item(x) for x in row)
        if spec.start == "ring":
            line = f"({body})@R0" if i == 0 else body
        else:  # flat rows: skip chains in row 1, turning chain after that, turn at the end
            # By default the turning chain is not counted: `3sk,14dc` in row 1 ("dc in 4th ch from hook"),
            # then `3ch,14dc`. Where the pattern says it counts as a stitch (spec.turn_counts) it is written
            # as that stitch: the row's stitches include it, and in row 1 there is one fewer chain to skip.
            if i == 0:
                lead = f"{skipped(spec) - spec.turn_counts}sk,"
            else:
                lead = "" if spec.turn_counts else TURNING_CHAIN[spec.stitch] + ","
            line = f"{lead}{body}" + ("" if i == last else ",turn")
        lines.append(line)
    return "\n".join(lines)


def _item(x) -> str:
    if isinstance(x, Repeat):
        return f"{x.times}*[{','.join(_item(i) for i in x.items)}]"
    name = {"st": x.stitch, "inc": f"{x.stitch}2inc", "dec": f"{x.stitch}2tog"}[x.kind]
    if x.n == 1:
        return name
    return f"{x.n}{name}" if x.kind == "st" else f"{x.n}*[{name}]"
