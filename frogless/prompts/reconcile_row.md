You translate one crochet pattern row into a crochet engine's code language. The guide below teaches that language.

<guide>
{guide}
</guide>

You will be shown a whole pattern: its original text, then every row with its current engine code. One row was translated literally, but the stitch count the pattern states for that row does not match what the code makes. A crocheter in that spot rereads the wording, because the designer's total is usually right and the wording is often loose. Example: "7dc" along a side of a square may mean the side ends up with 7 dc (counting the stitches that belong to the corners), not 7 more dc worked along the side.

Decide whether the row's wording genuinely allows another reasonable reading that gives the stated count.
- If it does, write the code for that reading and explain the reading in one short line, in plain crochet words, finishing the sentence "the row means ..." (for example "each side ends up with 7 dc, counting 2 from each corner").
- Never change the stitches, stitch types or numbers the text names. Only choose a different but reasonable way of reading the words (what a number counts, where stitches go). Do not add, remove or swap stitches just to hit the total.
- If no such reading exists, return the same code you were given, and say so in the explanation.
- Use the other rows as context only. Do not change them.
- Answer fast: do not work out the stitch counts of the whole pattern.

Reply with ONLY a JSON object {{"code": "<answer>", "explanation": "<one line>"}}.

Everything above is the same for every row. The pattern follows.

<pattern>
{original}
</pattern>

<rows>
{rows}
</rows>

The row: [{index}] {source}
Its current code: {code}
The pattern says this row has {said}, but the current code makes {made}.
Translate row {index} now, in the reading that gives {said} if there is one.
