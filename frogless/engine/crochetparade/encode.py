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
            lead = f"{skipped(spec)}sk" if i == 0 else TURNING_CHAIN[spec.stitch]
            line = f"{lead},{body}" + ("" if i == last else ",turn")
        lines.append(line)
    return "\n".join(lines)


def _item(x) -> str:
    if isinstance(x, Repeat):
        return f"{x.times}*[{','.join(_item(i) for i in x.items)}]"
    name = {"st": x.stitch, "inc": f"{x.stitch}2inc", "dec": f"{x.stitch}2tog"}[x.kind]
    if x.n == 1:
        return name
    return f"{x.n}{name}" if x.kind == "st" else f"{x.n}*[{name}]"
