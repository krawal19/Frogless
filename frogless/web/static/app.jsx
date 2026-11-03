// The Frogless page: pattern | result, Your pattern | Frogless corrected (only with corrections), picture, how we checked, developer panel (?dev=1).
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

const THEME_KEY = "frogless-theme";
function currentTheme() {
  const set = document.documentElement.getAttribute("data-theme");
  if (set === "dark" || set === "light") return set;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function ThemeToggle() {
  const [theme, setTheme] = useState(currentTheme);
  const flip = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* storage may be blocked */ }
    setTheme(next);
  };
  const label = theme === "dark" ? "Switch to light mode" : "Switch to dark mode";
  return (
    <button type="button" className="theme-toggle" onClick={flip} aria-label={label} title={label}>
      <Icon name={theme === "dark" ? "sun" : "moon"} size={20} />
    </button>
  );
}

function Header() {
  return (
    <header className="masthead">
      <div className="masthead-inner">
        <div className="brand">
          <Logo />
          <p>Know if a crochet pattern works before you pick up your hook</p>
        </div>
        <ThemeToggle />
      </div>
    </header>
  );
}

function InputCard({ text, setText, terms, setTerms, examples, onPick, onCheck, onStop, busy, running }) {
  const groups = { demo: "Demo patterns", general: "More examples" };
  const onKey = (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") onCheck(); };
  return (
    <section className="card input-card">
      <h2 className="panel-title"><label htmlFor="pattern">Your pattern</label></h2>
      <textarea id="pattern" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey}
                spellCheck={false} rows={9}
                placeholder="Paste a pattern and press Check" />
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
                     options={[{ value: "US", label: "US" }, { value: "UK", label: "UK" }]} />
        </div>
        <button type="button" className="primary" onClick={onCheck} disabled={busy || !text.trim()}>
          {busy ? <><span className="spinner light" />Checking…</> : "Check pattern"}
        </button>
        <button type="button" className="stop" onClick={onStop} disabled={!running}>
          <Icon name="stop" size={16} />Stop
        </button>
      </div>
    </section>
  );
}

function Panel({ title, sub, children, className = "" }) {
  return (
    <section className={`card pane ${className}`}>
      {title && <header className="pane-head"><h2>{title}</h2>{sub && <span>{sub}</span>}</header>}
      {children}
    </section>
  );
}

const STATUS_LINES = [
  "Counting every stitch twice…", "Untangling round 3…", "Asking the hook nicely…",
  "Checking the turning chains didn't sneak off…", "Frogging nothing (yet)…", "Weaving in loose ends…",
  "Measuring gauge with a very serious face…", "Fluffing the yarn…", "Whispering to the stitch markers…",
  "Making sure no stitch is hiding in the magic ring…", "Teaching the skein to behave…", "Tallying increases and decreases…",
  "Counting loops on the hook (just one, hopefully)…", "Brewing tea while the rows add up…",
];

function Checking({ elapsed }) {
  const [i, setI] = useState(() => Math.floor(Math.random() * STATUS_LINES.length));
  useEffect(() => {
    const t = setInterval(() => setI((n) => (n + 1) % STATUS_LINES.length), 2500);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="checking" role="status">
      <h3 className="checking-title">Checks can take a few minutes</h3>
      <div className="checking-body">
        <div className="lines" aria-hidden="true"><i /><i /><i /></div>
        <p className="status-line" key={i}>{STATUS_LINES[i]}</p>
      </div>
      <span className="elapsed mono">{elapsed} s</span>
    </div>
  );
}

function ResultCard({ busy, elapsed, error, result, sizesTabs, stopped }) {
  let body, empty = false;
  if (busy) {
    body = <Checking elapsed={elapsed} />;
  } else if (stopped) {
    body = (
      <div className="verdict unreadable" role="status">
        <span className="verdict-icon"><Icon name="stop" size={28} /></span>
        <div><div className="verdict-label">Stopped</div><p className="verdict-msg">Stopped. Nothing was changed.</p></div>
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
    empty = true;
    body = (
      <div className="empty-art">
        <img src="img/swatch.webp" alt="A crochet hook beside stitch symbols and crocheted rows" />
        <p>Verified results will show up here</p>
      </div>
    );
  }
  return <Panel title="Result" className={`result-card${empty ? " is-empty" : ""}`}>{sizesTabs}{body}</Panel>;
}

function App() {
  const [text, setText] = useState("");
  const [terms, setTerms] = useState("US");
  const [examples, setExamples] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState(null);       // the /api/check answer
  const [size, setSize] = useState(0);
  const [drawn, setDrawn] = useState({});       // size -> { state: "loading" | "done" | "failed", ...render answer }
  const [zoom, setZoom] = useState(null);
  const [stopped, setStopped] = useState(false);
  const jobs = useRef(new Set());   // ids of the running server jobs
  const run = useRef(0);            // bumped on every new check and on Stop, so answers of an older run are dropped
  const elapsed = useElapsed(busy);
  const resultsRef = useRef(null);
  const dev = new URLSearchParams(window.location.search).get("dev") === "1";

  useEffect(() => { Api.examples().then((r) => setExamples(r.examples || [])).catch(() => {}); }, []);

  const track = (id) => jobs.current.add(id);

  const draw = (id, index, mine) => {
    setDrawn((d) => ({ ...d, [index]: { state: "loading" } }));
    Api.render(id, index, track)
      .then((r) => { if (run.current === mine && r) setDrawn((d) => ({ ...d, [index]: { state: "done", ...r } })); })
      .catch((e) => { if (run.current === mine) setDrawn((d) => ({ ...d, [index]: { state: "failed", error: e.message } })); });
  };

  const onPick = (value) => {
    if (value !== "") setText(examples[Number(value)].text);
  };

  const onCheck = async () => {
    if (busy || !text.trim()) return;
    const mine = ++run.current;
    jobs.current = new Set();
    setBusy(true); setError(""); setStopped(false); setData(null); setDrawn({}); setSize(0);
    try {
      const r = await Api.check(text, terms, track);
      if (run.current !== mine || !r) return;
      setData(r);
      draw(r.id, 0, mine);
    } catch (e) {
      if (run.current === mine) setError(e.message);
    } finally {
      if (run.current === mine) setBusy(false);
    }
  };

  const onStop = () => {
    run.current += 1;
    const ids = [...jobs.current];
    jobs.current = new Set();
    ids.forEach((id) => Api.stop(id).catch(() => {}));
    setBusy(false); setError(""); setData(null); setDrawn({}); setSize(0); setStopped(true);
  };

  const pickSize = (i) => {
    setSize(i);
    if (data && !drawn[i]) draw(data.id, i, run.current);
  };

  const result = data && data.results[size];
  const render = drawn[size];
  const loading = !render || render.state === "loading";
  const failed = render && render.state === "failed" ? { error: render.error } : null;
  const done = render && render.state === "done";
  const fixed = result && result.corrected_status === "fixed";
  const drawing = Object.values(drawn).some((d) => d.state === "loading");
  const running = busy || drawing;

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
                     onPick={onPick} onCheck={onCheck} onStop={onStop} busy={busy} running={running} />
          <ResultCard busy={busy} elapsed={elapsed} error={error} result={result} sizesTabs={sizesTabs} stopped={stopped} />
        </div>

        {result && (
          <div ref={resultsRef} className="results">
            {fixed && (
              <Panel title="Your pattern vs Frogless corrected" sub="changed text is highlighted on both sides">
                <Compare written={result.written_lines} corrected={result.corrected_lines} rebuilt={result.corrected_source === "rebuilt"} />
              </Panel>
            )}
            <Panel className="pictures">
              <Picture key={`p${size}${fixed}`} loading={loading} onZoom={setZoom}
                       panes={fixed ? [{ label: "Your pattern", images: done ? render.written : failed },
                                       { label: "Frogless corrected", images: done ? render.corrected : failed }]
                                    : [{ label: "Your pattern", images: done ? render.written : failed }]} />
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
