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
    expand: <><path d="M12 4h4v4M8 16H4v-4M16 4l-5 5M4 16l5-5" /></>,
  };
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor"
         strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
  );
}

function Logo() {
  // three linked chain loops
  return (
    <svg className="logo" width="46" height="46" viewBox="0 0 44 44" aria-hidden="true">
      <rect width="44" height="44" rx="12" fill="var(--brand)" />
      <g fill="none" stroke="var(--brand-ink)" strokeWidth="3" strokeLinecap="round">
        <ellipse cx="13" cy="24" rx="6.5" ry="4.4" transform="rotate(-35 13 24)" />
        <ellipse cx="22" cy="19" rx="6.5" ry="4.4" transform="rotate(35 22 19)" />
        <ellipse cx="31" cy="24" rx="6.5" ry="4.4" transform="rotate(-35 31 24)" />
      </g>
    </svg>
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

function Banner({ result }) {
  const style = verdictStyle(result);
  const { fixes, footer } = groupFixes(result.fix_lines);
  // the fixes are listed below, so the headline stops before them
  const headline = fixes.length ? (result.user_message || "").replace(/\s*Suggested fix[\s\S]*$/, "") : result.user_message;
  const { main, extra } = splitMessage(headline);
  const notes = [...extra, ...(result.notes || [])];
  return (
    <section className={`banner ${style}`} aria-live="polite" role="status">
      <div className="banner-head">
        <span className="banner-icon"><Icon name={style} size={32} /></span>
        <div className="banner-text">
          <div className="banner-label">{VERDICT_LABEL[style]}</div>
          <p className="banner-msg">{main}</p>
        </div>
      </div>
      {fixes.length > 0 && (
        <ul className="fixes">
          {fixes.map((f, i) => (
            <li key={i}>
              <span className="fix-title">{f.title}</span>
              {f.reads && <code className="fix-reads">{f.reads}</code>}
            </li>
          ))}
          {footer && <li className="fix-footer"><Icon name="fix" size={16} />{footer}</li>}
        </ul>
      )}
      {notes.length > 0 && (
        <ul className="notes">
          {notes.map((n, i) => <li key={i}><Icon name="note" size={16} />{n}</li>)}
        </ul>
      )}
    </section>
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

function ChartPane({ images, loading, onZoom }) {
  const [view, setView] = useState("symbols");
  const options = [{ value: "symbols", label: "Chart" }, { value: "sketch", label: "Sketch" }];
  if (images && images.view_3d) options.push({ value: "view_3d", label: "3D" });
  const src = images && images[view];
  let body;
  if (loading) {
    body = <div className="chart-empty loading"><span className="spinner" /><span>Drawing the chart…</span></div>;
  } else if (images && src) {
    body = (
      <button type="button" className="chart-img" onClick={() => onZoom(src)} title="Enlarge">
        <img src={src} alt={view === "symbols" ? "Stitch chart" : view === "sketch" ? "Sketch of the piece" : "3D view"} />
        <span className="zoom"><Icon name="expand" size={16} /></span>
      </button>
    );
  } else {
    body = (
      <div className="chart-empty">
        <Icon name="image" size={26} />
        <span>{(images && images.error) ? `The chart could not be drawn: ${images.error}` : "No picture for this view."}</span>
      </div>
    );
  }
  return (
    <div className="chart">
      <div className="chart-bar">
        <span className="chart-title">Picture</span>
        <Segmented options={options} value={view} onChange={setView} label="Chart view" />
      </div>
      <div className="chart-box">{body}</div>
      {images && images.note && !loading && <p className="chart-note">{images.note}</p>}
    </div>
  );
}

// ---------- details ----------
const STAGE_NAME = {
  translate: "Translate", faithfulness: "Read-back check", reconcile: "Reconcile", ledger: "Stitch ledger",
  engine_verdict: "Engine check", review: "Review", shape: "Shape",
};

function seconds(n) { return `${(n || 0).toFixed(1)} s`; }

function byLabel(by) {
  if (by === "rules") return "rules";
  if (by === "model" || by === "counted by AI") return "AI";
  return by || "";
}

function RowTable({ rows }) {
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
              <td><span className={`by by-${byLabel(r.translated_by).toLowerCase()}`}>{byLabel(r.translated_by)}</span></td>
              <td className="wrap">{r.read_back || ""}</td>
              <td className="num mono">{r.stated ?? "–"}</td>
              <td className={`num mono${mismatch(r) ? " mismatch" : ""}`}>
                {r.computed ?? "–"}{mismatch(r) && <span className="sr"> (does not match)</span>}
              </td>
              <td className="wrap">
                {r.status !== "ok" && r.status !== "added" && <span className={`status st-${r.status.replace(/\s+/g, "-")}`}>{r.status}</span>}
                {r.note}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Timings({ timings, renderSeconds }) {
  const items = Object.keys(STAGE_NAME).filter((k) => (timings[k] || 0) > 0.005);
  const max = Math.max(0.1, ...items.map((k) => timings[k]), renderSeconds || 0);
  const bar = (name, value, key) => (
    <div className="t-row" key={key}>
      <span className="t-name">{name}</span>
      <span className="t-bar"><i style={{ width: `${Math.max(2, (value / max) * 100)}%` }} /></span>
      <span className="t-val mono">{seconds(value)}</span>
    </div>
  );
  return (
    <div className="timings">
      {items.map((k) => bar(STAGE_NAME[k], timings[k], k))}
      {renderSeconds != null && bar("Draw the charts", renderSeconds, "render")}
      <div className="t-total">
        <span>Check</span><b className="mono">{seconds(timings.total)}</b>
        {renderSeconds != null && <><span>Charts</span><b className="mono">{seconds(renderSeconds)}</b></>}
      </div>
    </div>
  );
}

function Details({ result, renderSeconds, totalCost, sizes }) {
  return (
    <details className="details">
      <summary><Icon name="chevron" size={18} /><span>Details</span>
        <small>row by row, shape hints, timings, cost</small></summary>
      <div className="details-body">
        <h4>Row by row</h4>
        <RowTable rows={result.rows} />
        <div className="details-grid">
          <div>
            <h4>Shape hints</h4>
            {result.shape_lines && result.shape_lines.length
              ? <ul className="plain">{result.shape_lines.map((l, i) => <li key={i}>{l.trim()}</li>)}</ul>
              : <p className="muted">No shape hints for this pattern.</p>}
            <h4>Cost of this check</h4>
            <p className="cost mono">${result.cost_usd.toFixed(4)}
              {sizes > 1 && <span className="muted"> this size · ${totalCost.toFixed(4)} all sizes</span>}</p>
            {result.terms && <p className="muted">Terms read as {result.terms}.</p>}
          </div>
          <div>
            <h4>Time per stage</h4>
            <Timings timings={result.timings} renderSeconds={renderSeconds} />
          </div>
        </div>
      </div>
    </details>
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

Object.assign(window, { Icon, Logo, Banner, PatternLines, ChartPane, Details, Lightbox, Segmented });
