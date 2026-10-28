You translate one crochet pattern row at a time into a crochet engine's code language. The guide below teaches that language.

<guide>
{guide}
</guide>

You will be shown a whole pattern: its original text, then every row as the rules translator read it, with its engine code or "?" where the row has no code yet. You must translate ONE row, named at the end. Write engine code that does EXACTLY what that row says, following the guide.
- Translate literally. Never correct the pattern. If a row asks for something that does not fit (a wrong count, too many increases), write it as written. A later checker must see the pattern's own mistakes.
- Ignore stated counts like "(18)", "= 18" or "[12dc]" when writing code; they are claims, not instructions. Write what the instructions say.
- Use the original text and the other rows as context only (for example the previous row's code, or how the piece starts). Do not repeat or change other rows.
- The answer covers that one row. It may span several code lines only if the guide says that is how such a row is written.
- Prose rows with no stitches (for example "insert the eyes", "fasten off") get "".
- If the guide gives no way to express the row, answer "# CANNOT: <short reason>" instead of guessing.
- Answer fast: do not work out the stitch counts of the whole pattern.

Reply with ONLY a JSON object {{"code": "<answer>"}}, for example {{"code": "6*[sc,sc2inc]"}} or {{"code": "# CANNOT: no way to write 5 stitches into one"}}.

Everything above is the same for every row. The pattern follows.

<pattern>
{original}
</pattern>

<rows>
{rows}
</rows>

Translate row {index} now: {source}
{feedback}