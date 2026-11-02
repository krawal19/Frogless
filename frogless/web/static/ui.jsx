// Small presentational pieces for the Frogless page.
const { useState, useEffect, useRef } = React;

// ---------- icons (stroke icons, 20px grid) ----------
function Icon({ name, size = 20 }) {
  const paths = {
    works: <><circle cx="10" cy="10" r="8" /><path d="M6.2 10.4l2.5 2.5 5-5.4" /></>,
    notes: <><circle cx="10" cy="10" r="8" /><path d="M6.2 10.4l2.5 2.5 5-5.4" /><circle cx="16" cy="4" r="2.2" className="dot" /></>,
    breaks: <><circle cx="10" cy="10" r="8" /><path d="M7 7l6 6M13 7l-6 6" /></>,
    ambiguous: <><circle cx="10" cy="10" r="8" /><path d="M7.8 8a2.3 2.3 0 114 1.4c-.8.8-1.8 1.1-1.8 2.4" /><path d="M10 14.4v.1" /></>,
    unreadable: <><circle cx="10" cy="10" r="8" /><path d="M6 10h8" strokeDasharray="1.5 2.5" /></>,
    fix: <><path d="M4 10.5l4 4 8-9" /></>,
    note: <><path d="M10 6v5M10 14v.1" /><circle cx="10" cy="10" r="8" /></>,
    chevron: <><path d="M6 8l4 4 4-4" /></>,
    image: <><rect x="3" y="4" width="14" height="12" rx="2" /><path d="M3 13l4-4 4 4 2-2 4 4" /></>,
    close: <><path d="M5 5l10 10M15 5L5 15" /></>,
    sun: <><circle cx="10" cy="10" r="3.4" /><path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4" /></>,
    moon: <><path d="M16.5 11.6A6.8 6.8 0 018.4 3.5a6.8 6.8 0 108.1 8.1z" /></>,
    stop: <><rect x="5" y="5" width="10" height="10" rx="2" /></>,
    expand: <><path d="M12 4h4v4M8 16H4v-4M16 4l-5 5M4 16l5-5" /></>,
  };
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor"
         strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
  );
}

function Logo() {
  return (
    <>
      <img className="brand-logo light" src="img/logo-light.png" srcSet="img/logo-light.png 1x, img/logo-light@2x.png 2x" alt="Frogless" height="80" />
      <img className="brand-logo dark" src="img/logo-dark.png" srcSet="img/logo-dark.png 1x, img/logo-dark@2x.png 2x" alt="" aria-hidden="true" height="80" />
    </>
  );
}

// ---------- the verdict ----------
const VERDICT_LABEL = {
  works: "Works", notes: "Works, with notes", breaks: "Breaks", ambiguous: "Depends on how you read it", unreadable: "Could not read it",
};

function verdictStyle(result) {
  const group = result.verdict.group;
  if (group === "works") {
    const msg = result.user_message || "";
    const withNotes = result.verdict.kind !== "works" || (result.notes || []).length > 0 || /,\s*if\b|⚠/.test(msg);
    return withNotes ? "notes" : "works";
  }
  return group;
}

// "✅ Works, if x. ⚠ note" -> { main, extra }: the emoji in the text are dropped, the page draws its own icons.
function splitMessage(message) {
  const clean = (s) => s.replace(/^[^\p{L}\p{N}"'(\[]+/u, "").trim();
  const [first, ...rest] = (message || "").split("⚠");
  const main = clean(first);
  const extra = rest.map((s) => s.trim()).filter(Boolean);
  return { main: main || (extra.shift() || ""), extra };
}

const SYMBOLS = /[✅⚠❌❓ⓘℹ]️?\s*/gu;
const stripSymbols = (s) => (s || "").replace(SYMBOLS, "").trim();

// a note block: bold colored heading (red = problem, yellow = check this, green = good news) and the text below
function NoteBlock({ title, body, tone }) {
  return (
    <div className={`note-block ${tone}`}>
      <div className="note-title">{title}</div>
      <p className="note-body">{body}</p>
    </div>
  );
}

// Pair each "Suggested fix ..." line with the indented "... would read" line that follows it.
function groupFixes(lines) {
  const fixes = []; let footer = "";
  (lines || []).forEach((line) => {
    if (/^\s+/.test(line) && fixes.length) fixes[fixes.length - 1].reads = line.trim();
    else if (/^Re-checked/.test(line)) footer = line;
    else fixes.push({ title: line.trim(), reads: "" });
  });
  return { fixes, footer };
}

function Verdict({ result }) {
  const style = verdictStyle(result);
  const { fixes, footer } = groupFixes(result.fix_lines);
  // the fixes are listed under "What we corrected", so the headline stops before them
  const headline = fixes.length ? (result.user_message || "").replace(/\s*Suggested fix[\s\S]*$/, "") : result.user_message;
  let { main } = splitMessage(headline);
  // a pattern that works with only notes: the notes are drawn as blocks below, so the headline stays short
  if (result.verdict.group === "works" && !/^(Works|Stitch|This pattern)/.test(main)) main = "Stitch counts check out.";
  const blocks = result.note_blocks || [];
  return (
    <div className="result-body">
      <div className={`verdict ${style}`} aria-live="polite" role="status">
        <span className="verdict-icon"><Icon name={style} size={30} /></span>
        <div>
          <div className="verdict-label">{VERDICT_LABEL[style]}</div>
          <p className="verdict-msg">{main}</p>
        </div>
      </div>
      {blocks.length > 0 && (
        <div className="note-blocks">
          {blocks.map((b, i) => <NoteBlock key={i} {...b} />)}
        </div>
      )}
      {fixes.length > 0 ? (
        <section className="sub">
          <h3>What we corrected</h3>
          <ul className="fixes">
            {fixes.map((f, i) => (
              <li key={i}>
                <span className="fix-title">{stripSymbols(f.title)}</span>
                {f.reads && <code className="fix-reads">{stripSymbols(f.reads)}</code>}
              </li>
            ))}
          </ul>
          {footer && <p className="fix-footer">{stripSymbols(footer)}</p>}
        </section>
      ) : null}
      {result.corrected_status === "fixed" && (
        <section className="sub">
          <h3>The corrected pattern</h3>
          <PatternLines lines={result.corrected_lines} />
          {result.corrected_source === "rebuilt" &&
            <p className="source-note">Rebuilt from how Frogless read each row, with the fix applied.</p>}
        </section>
      )}
    </div>
  );
}

// ---------- pattern text ----------
function PatternLines({ lines }) {
  return (
    <ol className="pattern">
      {lines.map((ln, i) => (
        <li key={i} className={`pl ${ln.mark || ""}${ln.text.trim() ? "" : " blank"}`}>
          <span className="pl-no" aria-hidden="true">{i + 1}</span>
          <span className="pl-text">{ln.text || " "}</span>
          {ln.note && (
            <span className="tag">
              <Icon name={ln.mark === "breaks" ? "breaks" : "fix"} size={14} />{ln.note}
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}

// ---------- As written | Corrected ----------
const FIX_TAIL = /\s*\[(?:suggested fix|works if|added)[\s\S]*$/i;

function lcsPairs(a, b) {
  const n = a.length, m = b.length;
  const t = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    t[i][j] = a[i] === b[j] ? t[i + 1][j + 1] + 1 : Math.max(t[i + 1][j], t[i][j + 1]);
  const out = []; let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push([i, j]); i++; j++; }
    else if (t[i + 1][j] >= t[i][j + 1]) i++; else j++;
  }
  return out;
}

// word-level diff of one changed row -> [leftParts, rightParts], each [{ t, hit }]
function wordDiff(a, b) {
  const x = a.split(/(\s+)/).filter(Boolean), y = b.split(/(\s+)/).filter(Boolean);
  const pairs = lcsPairs(x, y);
  const left = [], right = []; let i = 0, j = 0;
  const flush = (ei, ej) => {
    if (i < ei) left.push({ t: x.slice(i, ei).join(""), hit: true });
    if (j < ej) right.push({ t: y.slice(j, ej).join(""), hit: true });
  };
  pairs.forEach(([pi, pj]) => { flush(pi, pj); left.push({ t: x[pi] }); right.push({ t: y[pj] }); i = pi + 1; j = pj + 1; });
  flush(x.length, y.length);
  return [left, right];
}

function alignRows(written, corrected) {
  const norm = (l) => l.text.replace(FIX_TAIL, "").trim().replace(/\s+/g, " ");
  const tagOf = (l) => { const m = l.text.match(FIX_TAIL); return m ? m[0].trim().replace(/^\[|\]$/g, "") : ""; };
  const w = written.map(norm), c = corrected.map(norm);
  const rows = []; let i = 0, j = 0;
  const gap = (ei, ej) => {
    while (i < ei || j < ej) {
      const hasW = i < ei, hasC = j < ej;
      if (hasW && hasC) {
        const [l, r] = wordDiff(w[i], c[j]);
        rows.push({ kind: "changed", left: l, right: r, ln: i + 1, rn: j + 1 }); i++; j++;
      } else if (hasW) { rows.push({ kind: "removed", left: [{ t: w[i], hit: true }], ln: i + 1 }); i++; }
      else { rows.push({ kind: "added", right: [{ t: c[j], hit: true }], rn: j + 1 }); j++; }
    }
  };
  lcsPairs(w, c).forEach(([pi, pj]) => {
    gap(pi, pj);
    rows.push({ kind: "same", left: [{ t: w[pi] }], right: [{ t: c[pj] }], ln: pi + 1, rn: pj + 1 }); i = pi + 1; j = pj + 1;
  });
  gap(w.length, c.length);
  return rows;
}

// A rebuilt pattern is worded differently from the written one, so rows are paired by their number and only
// the rows a fix touched are highlighted (as a whole).
function alignByNumber(written, corrected) {
  const num = (t) => { const m = t.match(/^\s*(?:rows?|rounds?|rnds?|r)\s*(\d+)/i); return m ? Number(m[1]) : null; };
  const used = new Set(); const rows = [];
  const cs = corrected.filter((l) => !/^\s*note:/i.test(l.text));
  written.forEach((l, i) => {
    const n = num(l.text);
    const j = n == null ? -1 : cs.findIndex((c, k) => !used.has(k) && num(c.text) === n);
    const left = l.text.trim().replace(/\s+/g, " ");
    if (j < 0) { rows.push({ kind: "same", left: [{ t: left }], right: [], ln: i + 1 }); return; }
    used.add(j);
    const c = cs[j], right = c.text.replace(FIX_TAIL, "").trim();
    const fixedRow = FIX_TAIL.test(c.text);
    rows.push({ kind: fixedRow ? "changed" : "same", ln: i + 1, rn: j + 1,
                left: [{ t: left, hit: fixedRow }], right: [{ t: right, hit: fixedRow }] });
  });
  // rows the checker added (e.g. "Make a magic ring") keep their place in the corrected pattern: before the next paired row
  const extraRow = (c, j) => ({ kind: FIX_TAIL.test(c.text) ? "added" : "extra", right: [{ t: c.text.replace(FIX_TAIL, "").trim(), hit: FIX_TAIL.test(c.text) }], rn: j + 1 });
  const before = new Map();
  cs.forEach((c, j) => { if (!used.has(j)) { let n = j + 1; while (n < cs.length && !used.has(n)) n++; const key = n < cs.length ? n : -1; before.set(key, [...(before.get(key) || []), extraRow(c, j)]); } });
  const out = [];
  rows.forEach((r) => { if (r.rn != null && before.has(r.rn - 1)) out.push(...before.get(r.rn - 1)); out.push(r); });
  if (before.has(-1)) out.push(...before.get(-1));
  return out;
}

function Parts({ parts, cls }) {
  return <>{(parts || []).map((p, i) => p.hit ? <mark key={i} className={cls}>{p.t}</mark> : <span key={i}>{p.t}</span>)}</>;
}

function Compare({ written, corrected, rebuilt }) {
  const rows = (rebuilt ? alignByNumber : alignRows)(written.filter((l) => l.text.trim()), corrected.filter((l) => l.text.trim()));
  return (
    <div className="cmp" role="table" aria-label="Your pattern compared with Frogless corrected">
      <div className="cmp-head" role="row"><h3 role="columnheader">Your pattern</h3><h3 role="columnheader">Frogless corrected</h3></div>
      {rows.map((r, k) => (
        <div key={k} className={`cmp-row ${r.kind}`} role="row">
          <div className="cmp-cell left" role="cell">
            {r.ln && <span className="pl-no" aria-hidden="true">{r.ln}</span>}
            <span className="pl-text"><Parts parts={r.left} cls="del" /></span>
            {r.kind === "removed" && <span className="tag gone">removed</span>}
          </div>
          <div className="cmp-cell right" role="cell">
            {r.rn && <span className="pl-no" aria-hidden="true">{r.rn}</span>}
            <span className="pl-text"><Parts parts={r.right} cls="ins" /></span>
            {r.kind === "added" && <span className="tag add">added row</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------- charts ----------
function Segmented({ options, value, onChange, label }) {
  return (
    <div className="seg" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value}
                className={value === o.value ? "on" : ""} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}

function ChartBox({ images, loading, view, onZoom }) {
  const src = images && images[view];
  if (loading) return <div className="chart-box"><div className="chart-empty loading"><span className="spinner" /><span>Drawing the chart…</span></div></div>;
  if (images && src) {
    return (
      <div className="chart-box">
        <button type="button" className="chart-img" onClick={() => onZoom(src)} title="Enlarge">
          <img src={src} alt={view === "symbols" ? "Stitch chart" : view === "sketch" ? "Sketch of the piece" : "3D view"} />
          <span className="zoom"><Icon name="expand" size={16} /></span>
        </button>
      </div>
    );
  }
  return (
    <div className="chart-box">
      <div className="chart-empty">
        <Icon name="image" size={26} />
        <span>{(images && images.error) ? `The chart could not be drawn: ${images.error}` : "No picture for this view."}</span>
      </div>
    </div>
  );
}

// panes: [{ label, images }]; one pane when nothing was corrected, two (original | corrected) otherwise. One shared toggle,
// on the same line as the column headings.
function Picture({ panes, loading, onZoom }) {
  const [view, setView] = useState("symbols");
  const options = [{ value: "symbols", label: "Chart" }, { value: "sketch", label: "Sketch" }];
  if (panes.some((p) => p.images && p.images.view_3d)) options.push({ value: "view_3d", label: "3D" });
  const tabs = <Segmented options={options} value={view} onChange={setView} label="Picture view" />;
  const two = panes.length > 1;
  return (
    <div className="chart">
      <div className={`chart-cols chart-heads n${panes.length}`}>
        {panes.map((p, i) => (
          <div key={i} className="chart-head">
            <h3>{p.label}</h3>
            {i === panes.length - 1 && tabs}
          </div>
        ))}
      </div>
      {two && <p className="chart-hint">Small fixes may look almost the same in the pictures; the changes are listed above.</p>}
      <div className={`chart-cols n${panes.length}`}>
        {panes.map((p, i) => (
          <div key={i} className="chart-col">
            <ChartBox images={p.images} loading={loading} view={view} onZoom={onZoom} />
            {p.images && p.images.note && !loading && <p className="chart-note">{p.images.note}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------- details ----------
const STAGE_NAME = {
  translate: "Translate", faithfulness: "Read-back check", reconcile: "Reconcile", ledger: "Stitch ledger",
  engine_verdict: "Engine check", review: "Review", shape: "Shape",
};

function seconds(n) { return `${(n || 0).toFixed(1)} s`; }

function byLabel(by, model) {
  if (by === "rules") return "rules";
  if (by === "model") return model || "model";
  if (by === "counted") return `counted by ${model || "model"}`;
  return by || "";
}

function byClass(by) { return by === "model" || by === "counted" ? "by-ai" : `by-${by}`; }

function RowTable({ rows, model }) {
  const mismatch = (r) => r.stated != null && r.computed != null && r.stated !== r.computed;
  return (
    <div className="table-wrap">
      <table className="rows">
        <thead>
          <tr><th className="num">Row</th><th>As written</th><th>Read by</th><th>Read back as</th>
            <th className="num">Pattern says</th><th className="num">Frogless counts</th><th>Note</th></tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={r.status === "breaks" ? "is-breaks" : r.status === "added" ? "is-added" : ""}>
              <td className="num mono">{r.number ?? "–"}</td>
              <td className="mono wrap">{r.text}</td>
              <td><span className={`by ${byClass(r.translated_by)}`}>{byLabel(r.translated_by, model)}</span>
                {r.double_checked && <span className="dc" title="The reading was turned back into words and compared, or counted a second way">double-checked</span>}</td>
              <td className="wrap">{r.read_back || ""}</td>
              <td className="num mono">{r.stated ?? "–"}</td>
              <td className={`num mono${mismatch(r) ? " mismatch" : ""}`}>
                {r.computed ?? "–"}{mismatch(r) && <span className="sr"> (does not match)</span>}
              </td>
              <td className="wrap">
                {r.status !== "ok" && r.status !== "added" && <span className={`status st-${r.status.replace(/\s+/g, "-")}`}>{STATUS_WORDS[r.status] || r.status}</span>}
                {r.note}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const STATUS_WORDS = { "not checked": "Not checked", "check the reading": "Check the reading", "after the break": "After the break", breaks: "Breaks here" };

function HowWeChecked({ result }) {
  return (
    <details className="details">
      <summary><Icon name="chevron" size={18} /><span>How we checked</span>
        <small>every row, and what we noticed about the shape</small></summary>
      <div className="details-body">
        <p className="muted">Each row was read by fixed rules or, when the wording was unusual, by {result.model || "a language model"}. Where possible the reading was
          turned back into words and compared with what you wrote (double-checked).</p>
        <RowTable rows={result.rows} model={result.model} />
        <h4>Shape hints</h4>
        {result.shape_lines && result.shape_lines.length
          ? <ul className="plain">{result.shape_lines.map((l, i) => <li key={i}>{l.trim()}</li>)}</ul>
          : <p className="muted">No shape hints for this pattern.</p>}
        {result.terms && <p className="muted">Terms read as {result.terms}.</p>}
      </div>
    </details>
  );
}

function DevPanel({ result, data, renderSeconds, size }) {
  const timings = result.timings || {};
  const items = Object.keys(STAGE_NAME).filter((k) => (timings[k] || 0) > 0.005);
  const max = Math.max(0.1, ...items.map((k) => timings[k]), renderSeconds || 0);
  const bar = (name, value, key) => (
    <div className="t-row" key={key}>
      <span className="t-name">{name}</span>
      <span className="t-bar"><i style={{ width: `${Math.max(2, (value / max) * 100)}%` }} /></span>
      <span className="t-val mono">{seconds(value)}</span>
    </div>
  );
  const facts = [
    ["Check time", seconds(timings.total)],
    ["Render time", renderSeconds != null ? seconds(renderSeconds) : "drawing…"],
    ["Cost of this check", `$${result.cost_usd.toFixed(4)}`],
    ...(data.sizes > 1 ? [["Cost, all sizes", `$${data.cost_usd.toFixed(4)}`]] : []),
    ["Check id", data.id], ["Size", `${size + 1} of ${data.sizes}`],
    ["Verdict kind", `${result.verdict.kind} (row ${result.verdict.row ?? "-"})`],
    ["Corrected", `${result.corrected_status}${result.corrected_source ? ` (${result.corrected_source})` : ""}`],
    ["Terms", result.terms || "-"],
  ];
  return (
    <section className="card dev" aria-label="Developer panel">
      <header className="pane-head"><h2>Developer</h2><span>only shown with ?dev=1</span></header>
      <div className="dev-grid">
        <div className="timings">{items.map((k) => bar(STAGE_NAME[k], timings[k], k))}
          {renderSeconds != null && bar("Draw the pictures", renderSeconds, "render")}</div>
        <dl className="facts">{facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd className="mono">{v}</dd></div>)}</dl>
      </div>
    </section>
  );
}

function Lightbox({ src, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  if (!src) return null;
  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label="Enlarged chart" onClick={onClose}>
      <button type="button" className="lb-close" onClick={onClose} aria-label="Close"><Icon name="close" /></button>
      <img src={src} alt="Enlarged chart" onClick={(e) => e.stopPropagation()} />
    </div>
  );
}

Object.assign(window, { Icon, Logo, Verdict, PatternLines, Compare, Picture, HowWeChecked, DevPanel, Lightbox, Segmented });
