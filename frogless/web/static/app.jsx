// The Frogless page: pattern | result, As written | Corrected (only with corrections), picture, how we checked, developer panel (?dev=1).
// (useState, useEffect, useRef and the components come from ui.jsx.)
const STAGES = ["translate", "check", "review"];

function useElapsed(running) {
  const [s, setS] = useState(0);
  useEffect(() => {
    if (!running) return undefined;
    const start = Date.now();
    setS(0);
    const t = setInterval(() => setS(Math.floor((Date.now() - start) / 1000)), 500);
    return () => clearInterval(t);
  }, [running]);
  return s;
}

function Header() {
  return (
    <header className="masthead">
      <div className="masthead-inner">
        <Logo />
        <div>
          <h1>Frogless</h1>
          <p>Know if a crochet pattern works before you pick up your hook</p>
        </div>
      </div>
    </header>
  );
}

function InputCard({ text, setText, terms, setTerms, examples, onPick, onCheck, busy }) {
  const groups = { dev: "Development patterns", smoke: "Smoke tests" };
  const onKey = (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") onCheck(); };
  return (
    <section className="card input-card">
      <h2 className="panel-title"><label htmlFor="pattern">Your pattern</label></h2>
      <textarea id="pattern" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey}
                spellCheck={false} rows={9}
                placeholder={"Round 1: 6 sc in a magic ring (6)\nRound 2: 2 sc in each st around (12)\nRound 3: *sc, 2 sc in next st* around (18)"} />
      <div className="controls">
        <div className="ctl">
          <label htmlFor="examples" className="field-label">Examples</label>
          <div className="select-wrap">
            <select id="examples" value="" onChange={(e) => onPick(e.target.value)} disabled={busy}>
              <option value="">{examples.length ? "Load an example…" : "No examples found"}</option>
              {Object.keys(groups).map((g) => {
                const list = examples.map((ex, i) => ({ ex, i })).filter(({ ex }) => ex.group === g);
                return list.length ? (
                  <optgroup key={g} label={groups[g]}>
                    {list.map(({ ex, i }) => <option key={i} value={i}>{ex.name}</option>)}
                  </optgroup>
                ) : null;
              })}
            </select>
            <Icon name="chevron" size={16} />
          </div>
        </div>
        <div className="ctl">
          <span className="field-label">Terms</span>
          <Segmented label="Terms" value={terms} onChange={setTerms}
                     options={[{ value: "auto", label: "Auto" }, { value: "US", label: "US" }, { value: "UK", label: "UK" }]} />
        </div>
        <div className="spacer" />
        <button type="button" className="primary" onClick={onCheck} disabled={busy || !text.trim()}>
          {busy ? <><span className="spinner light" />Checking…</> : "Check pattern"}
        </button>
      </div>
    </section>
  );
}

function Panel({ title, sub, children, className = "" }) {
  return (
    <section className={`card pane ${className}`}>
      <header className="pane-head"><h2>{title}</h2>{sub && <span>{sub}</span>}</header>
      {children}
    </section>
  );
}

function ResultCard({ busy, elapsed, error, result, sizesTabs }) {
  let body;
  if (busy) {
    body = (
      <div className="progress" role="status">
        <span className="bar"><i /></span>
        <span>Checking… <b>{STAGES.join(" → ")}</b></span>
        <span className="elapsed mono">{elapsed} s</span>
      </div>
    );
  } else if (error) {
    body = (
      <div className="verdict unreadable" role="alert">
        <span className="verdict-icon"><Icon name="breaks" size={30} /></span>
        <div><div className="verdict-label">Could not check</div><p className="verdict-msg">{error}</p></div>
      </div>
    );
  } else if (result) {
    body = <Verdict result={result} />;
  } else {
    body = <div className="empty"><Icon name="note" size={26} /><div><b>Nothing checked yet</b><p>Paste a pattern and press Check pattern. The verdict and any corrections appear here.</p></div></div>;
  }
  return <Panel title="Result" className="result-card">{sizesTabs}{body}</Panel>;
}

function App() {
  const [text, setText] = useState("");
  const [terms, setTerms] = useState("auto");
  const [examples, setExamples] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState(null);       // the /api/check answer
  const [size, setSize] = useState(0);
  const [drawn, setDrawn] = useState({});       // size -> { state: "loading" | "done" | "failed", ...render answer }
  const [zoom, setZoom] = useState(null);
  const elapsed = useElapsed(busy);
  const resultsRef = useRef(null);
  const dev = new URLSearchParams(window.location.search).get("dev") === "1";

  useEffect(() => { Api.examples().then((r) => setExamples(r.examples || [])).catch(() => {}); }, []);

  const draw = (id, index) => {
    setDrawn((d) => ({ ...d, [index]: { state: "loading" } }));
    Api.render(id, index)
      .then((r) => setDrawn((d) => ({ ...d, [index]: { state: "done", ...r } })))
      .catch((e) => setDrawn((d) => ({ ...d, [index]: { state: "failed", error: e.message } })));
  };

  const onPick = (value) => {
    if (value !== "") setText(examples[Number(value)].text);
  };

  const onCheck = async () => {
    if (busy || !text.trim()) return;
    setBusy(true); setError(""); setData(null); setDrawn({}); setSize(0);
    try {
      const r = await Api.check(text, terms);
      setData(r);
      draw(r.id, 0);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const pickSize = (i) => {
    setSize(i);
    if (data && !drawn[i]) draw(data.id, i);
  };

  const result = data && data.results[size];
  const render = drawn[size];
  const loading = !render || render.state === "loading";
  const failed = render && render.state === "failed" ? { error: render.error } : null;
  const done = render && render.state === "done";
  const fixed = result && result.corrected_status === "fixed";

  const sizesTabs = data && data.sizes > 1 && (
    <div className="sizes" role="tablist" aria-label="Sizes">
      {data.results.map((r, i) => (
        <button key={i} type="button" role="tab" aria-selected={i === size} className={i === size ? "on" : ""} onClick={() => pickSize(i)}>
          {r.label || `Size ${i + 1}`}
        </button>
      ))}
    </div>
  );

  return (
    <>
      <Header />
      <main className="page">
        <div className="top">
          <InputCard text={text} setText={setText} terms={terms} setTerms={setTerms} examples={examples}
                     onPick={onPick} onCheck={onCheck} busy={busy} />
          <ResultCard busy={busy} elapsed={elapsed} error={error} result={result} sizesTabs={sizesTabs} />
        </div>

        {result && (
          <div ref={resultsRef} className="results">
            {fixed && (
              <Panel title="As written | Corrected" sub="changed text is highlighted on both sides">
                <Compare written={result.written_lines} corrected={result.corrected_lines} rebuilt={result.corrected_source === "rebuilt"} />
              </Panel>
            )}
            <Panel title="Picture" sub={fixed ? "original and corrected, side by side" : "of the pattern as written"}>
              <Picture key={`p${size}${fixed}`} loading={loading} onZoom={setZoom}
                       panes={fixed ? [{ label: "Original (as written)", images: done ? render.written : failed },
                                       { label: "Corrected", images: done ? render.corrected : failed }]
                                    : [{ label: "As written", images: done ? render.written : failed }]} />
            </Panel>
            {dev && <HowWeChecked result={result} />}
            {dev && <DevPanel result={result} data={data} size={size} renderSeconds={done ? render.render_seconds : null} />}
          </div>
        )}
      </main>
      <footer className="foot">Frogless checks the stitch counts and shape of a written pattern. It cannot see your tension or your yarn.</footer>
      <Lightbox src={zoom} onClose={() => setZoom(null)} />
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
