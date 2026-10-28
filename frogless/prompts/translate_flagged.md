You translate crochet pattern rows into a crochet engine's code language. The guide below teaches that language.

<guide>
{guide}
</guide>

Below is one pattern. `original` is the pattern text exactly as written. `rows` is what a rules-based translator produced, one entry per row with `row`, `text` (lightly normalized), `flagged` and `code`. Rows with `flagged: false` already have engine code. Rows with `flagged: true` have `code: null` because the translator could not read them.

<pattern>
{pattern}
</pattern>

For every flagged row, write engine code that does EXACTLY what that row says, following the guide. Use the original text and the neighbouring rows as context (for example the previous row's stitch count and the ring or start).
- Translate literally. Never correct the pattern. If a row asks for something that does not fit (a wrong count, too many increases), write it as written. A later checker must see the pattern's own mistakes.
- Ignore stated counts like "(18)", "= 18" or "[12dc]" when writing code; they are claims, not instructions. Write what the instructions say.
- Each answer covers one row. It may span several code lines only if the guide says that is how such a row is written.
- Prose rows with no stitches (for example "insert the eyes", "fasten off") get "".
- If the guide gives no way to express a row, answer "# CANNOT: <short reason>" instead of guessing.

Reply with ONLY a JSON object mapping each flagged row number (as a string) to its answer, for example:
{{"3": "6*[sc,sc2inc]", "4": "# CANNOT: no way to write 5 stitches into one"}}
