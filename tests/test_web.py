"""The web page and API, with the checker and the drawing mocked: no model calls, no browser."""

from fastapi.testclient import TestClient

from frogless.patterns.terms import Terms
from frogless.pipeline.report import Fix, PatternReport, RowResult, Verdict
from frogless.web import api

TEXT = "Round 1: 6 sc in a magic ring (6)\nRound 2: 2 sc in each st around (13)\nRound 3: sc around (13)"


def _report(fixed: bool = True) -> PatternReport:
    rows = [
        RowResult(0, "6 sc in a magic ring", code="ring.R0", synthetic=True),
        RowResult(1, "Round 1: 6 sc in a magic ring (6)", code="R1: sc6", english="6 sc in the ring"),
        RowResult(2, "Round 2: 2 sc in each st around (13)", code="R2: inc6", origin="model", english="inc in each st"),
        RowResult(3, "Round 3: sc around (13)", code="", status="flagged", note="not recognized"),
    ]
    fix = Fix(row=2, original="2 sc in each st around (13)", fixed_text="Round 2: 2 sc in each st around (12)",
              explanation="the count is 12")
    v = Verdict(kind="breaks", message="Round 2: the pattern says 13, but the instructions make 12", row=2,
                fixes=[fix] if fixed else [])
    report = PatternReport(text=TEXT, rows=rows, verdict=v, stated={1: 6, 2: 13}, computed={1: 6, 2: 12},
                           cost_usd=0.0123, terms=Terms("US", []))
    report.timings = {"translate": 1.5, "review": 2.0, "total": 4.0}
    return report


def _client(monkeypatch, fixed: bool = True) -> TestClient:
    calls = []

    def fake_check(text, **kw):
        calls.append((text, kw))
        return _report(fixed)

    monkeypatch.setattr("frogless.pipeline.check.check_pattern", fake_check)
    monkeypatch.setattr(api.output, "clean_pattern", lambda r: "Round 1: sc 6. (6)")
    monkeypatch.setattr(api.output, "corrected_pattern",
                        lambda r: TEXT.replace("(13)\nRound 3", "(12)  [suggested fix: change 13 to 12]\nRound 3", 1) if fixed else None)
    client = TestClient(api.create_api())
    client.calls = calls
    return client


def test_check_returns_everything_the_page_shows(monkeypatch):
    client = _client(monkeypatch)
    res = client.post("/api/check?wait=1", json={"text": TEXT, "terms": "UK"})
    assert res.status_code == 200
    body = res.json()
    assert client.calls[0][1]["terms"] == "UK"
    assert body["id"] and body["sizes"] == 1 and len(body["results"]) == 1
    assert body["verdict"] == {"kind": "breaks", "group": "breaks", "row": 2}
    assert body["user_message"].startswith("❌ Breaks at Round 2")
    assert any("Suggested fix" in line for line in body["fix_lines"])
    assert body["shape_lines"] == [] and body["notes"] == []
    assert body["corrected_status"] == "fixed" and "[suggested fix" in body["corrected_pattern"]
    assert body["clean_pattern"].startswith("Round 1")
    assert set(body["timings"]) >= {"translate", "faithfulness", "reconcile", "ledger", "engine_verdict", "review", "shape", "total"}
    assert body["timings"]["total"] == 4.0 and body["cost_usd"] == 0.0123


def test_row_table_and_marked_lines(monkeypatch):
    body = _client(monkeypatch).post("/api/check?wait=1", json={"text": TEXT}).json()
    rows = body["rows"]
    assert [r["number"] for r in rows] == [None, 1, 2, 3]
    r2 = rows[2]
    assert (r2["translated_by"], r2["stated"], r2["computed"], r2["status"]) == ("model", 13, 12, "breaks")
    assert rows[3]["status"] == "not checked"
    marks = [line["mark"] for line in body["written_lines"]]
    assert marks == ["", "breaks", ""]  # the breaking row is marked; its fix is on the same row
    assert [line["mark"] for line in body["corrected_lines"]] == ["", "fix", ""]


def test_no_fix_and_empty_text(monkeypatch):
    client = _client(monkeypatch, fixed=False)
    body = client.post("/api/check?wait=1", json={"text": TEXT}).json()
    assert body["corrected_status"] == "no_fix" and body["corrected_pattern"] is None
    assert client.post("/api/check?wait=1", json={"text": "  "}).status_code == 400
    assert client.post("/api/check?wait=1", json={"text": TEXT, "terms": "French"}).status_code == 422


def test_render_serves_images_from_logs_web(monkeypatch, tmp_path):
    client = _client(monkeypatch)
    monkeypatch.setattr(api, "WEB_DIR", tmp_path)
    client = TestClient(api.create_api())
    monkeypatch.setattr("frogless.pipeline.check.check_pattern", lambda text, **kw: _report())
    check_id = client.post("/api/check?wait=1", json={"text": TEXT}).json()["id"]

    def fake_chart(report, out_dir, name):
        out_dir.mkdir(parents=True, exist_ok=True)
        sym, sk = out_dir / f"{name}_symbols.png", out_dir / f"{name}_connectivity.png"
        sym.write_bytes(b"png"), sk.write_bytes(b"png")
        return {"chart": str(sym), "symbols": str(sym), "connectivity": str(sk), "overlay": None, "view": None,
                "error": None, "note": "", "kind": "chart"}

    monkeypatch.setattr(api.output, "written_chart", fake_chart)
    monkeypatch.setattr(api.output, "corrected_chart", fake_chart)
    res = client.post(f"/api/render/{check_id}?wait=1")
    assert res.status_code == 200
    body = res.json()
    assert body["written"]["symbols"] == f"/files/{check_id}/size0/written_symbols.png"
    assert body["corrected"]["sketch"] == f"/files/{check_id}/size0/corrected_connectivity.png"
    assert body["render_seconds"] >= 0
    assert client.get(body["written"]["symbols"]).content == b"png"
    assert client.post("/api/render/nope?wait=1").status_code == 404


def test_multi_size_gives_one_result_per_size(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr("frogless.pipeline.check.check_pattern_sizes",
                        lambda text, **kw: [("Small", _report()), ("Large", _report(False))])
    body = client.post("/api/check?wait=1", json={"text": TEXT}).json()
    assert [r["label"] for r in body["results"]] == ["Small", "Large"]
    assert body["results"][1]["corrected_status"] == "no_fix"
    assert body["cost_usd"] == 0.0246


def test_page_and_static_files_are_served(monkeypatch):
    client = _client(monkeypatch)
    page = client.get("/")
    assert page.status_code == 200 and "react" in page.text and "app.jsx" in page.text
    for name in ("styles.css", "api.jsx", "ui.jsx", "app.jsx"):
        assert client.get(f"/{name}").status_code == 200
    assert client.get("/api/examples").status_code == 200  # the routes still win over the static mount


def test_examples_are_read_at_run_time(monkeypatch, tmp_path):
    dev, smoke = tmp_path / "dev", tmp_path / "smoke"
    dev.mkdir(), smoke.mkdir()
    (dev / "b.txt").write_text("Round 1: sc 6", encoding="utf-8")
    (dev / "a.txt").write_text("Round 1: sc 12", encoding="utf-8")
    (dev / "skip.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(api, "EXAMPLE_DIRS", (("dev", dev), ("smoke", smoke), ("gone", tmp_path / "missing")))
    client = _client(monkeypatch)
    assert client.get("/api/examples").json()["examples"] == [
        {"name": "a", "group": "dev", "text": "Round 1: sc 12"}, {"name": "b", "group": "dev", "text": "Round 1: sc 6"}]
    (smoke / "c.txt").write_text("Row 1: dc 6", encoding="utf-8")  # a file added later shows up on the next call
    assert [e["name"] for e in client.get("/api/examples").json()["examples"]] == ["a", "b", "c"]


def test_fix_that_cannot_be_placed_shows_the_rebuilt_pattern(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(api.output, "corrected_pattern", lambda r: None)
    monkeypatch.setattr(api.output, "clean_pattern", lambda r: "Round 1: sc 6. (6)\nRound 2: sc 12. (12) [suggested fix: x]")
    body = client.post("/api/check?wait=1", json={"text": TEXT}).json()
    assert body["corrected_pattern"] is None and body["corrected_source"] == "rebuilt"
    assert [line["mark"] for line in body["corrected_lines"]] == ["", "fix"]


# ---- jobs: a check or a drawing runs in its own process; the page polls and can stop it ----
class _FakeProc:
    """Stands in for a worker process: the work runs in a thread, terminate() is recorded."""

    def __init__(self, target, args, block=None):
        import threading
        self.terminated, self.pid = False, None
        self.block = block
        self.thread = threading.Thread(target=self._run, args=(target, args), daemon=True)
        self.thread.start()

    def _run(self, target, args):
        if self.block is not None:
            self.block.wait(5)
        target(*args)

    def is_alive(self):
        return self.thread.is_alive() and not self.terminated

    def terminate(self):
        self.terminated = True


def _fake_launch(monkeypatch, block=None):
    import queue
    procs = []

    def launch(target, args):
        out = queue.Queue()
        proc = _FakeProc(target, (out, *args), block)
        procs.append(proc)
        return proc, out

    monkeypatch.setattr(api, "_launch", launch)
    return procs


def _wait_done(client, job, tries=100):
    import time
    for _ in range(tries):
        body = client.get(f"/api/job/{job}").json()
        if body["state"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_check_runs_as_a_job_and_the_page_polls_it(monkeypatch):
    client = _client(monkeypatch)
    _fake_launch(monkeypatch)
    res = client.post("/api/check", json={"text": TEXT, "terms": "UK"})
    assert res.status_code == 200 and set(res.json()) == {"job"}
    body = _wait_done(client, res.json()["job"])
    assert body["state"] == "done" and body["kind"] == "check"
    assert body["result"]["verdict"]["kind"] == "breaks" and body["result"]["id"]
    assert client.calls[0][1]["terms"] == "UK"
    assert client.get("/api/job/nope").status_code == 404
    assert client.post("/api/check", json={"text": " "}).status_code == 400


def test_a_failing_check_job_reports_the_error(monkeypatch):
    client = _client(monkeypatch)
    _fake_launch(monkeypatch)

    def boom(text, **kw):
        raise RuntimeError("model unreachable")

    monkeypatch.setattr("frogless.pipeline.check.check_pattern", boom)
    body = _wait_done(client, client.post("/api/check", json={"text": TEXT}).json()["job"])
    assert body["state"] == "error" and "model unreachable" in body["error"]


def test_render_runs_as_a_job(monkeypatch, tmp_path):
    client = _client(monkeypatch)
    monkeypatch.setattr(api, "WEB_DIR", tmp_path)
    _fake_launch(monkeypatch)
    check_id = _wait_done(client, client.post("/api/check", json={"text": TEXT}).json()["job"])["result"]["id"]

    def fake_chart(report, out_dir, name):
        return {"symbols": str(tmp_path / check_id / "size0" / f"{name}_symbols.png"), "error": None, "note": ""}

    monkeypatch.setattr(api.output, "written_chart", fake_chart)
    monkeypatch.setattr(api.output, "corrected_chart", fake_chart)
    body = _wait_done(client, client.post(f"/api/render/{check_id}").json()["job"])
    assert body["state"] == "done" and body["kind"] == "render"
    assert body["result"]["written"]["symbols"] == f"/files/{check_id}/size0/written_symbols.png"
    assert body["result"]["corrected"]["symbols"].endswith("corrected_symbols.png")


def test_stop_terminates_the_check_and_its_drawing(monkeypatch):
    import threading
    client = _client(monkeypatch)
    gate = threading.Event()
    procs = _fake_launch(monkeypatch, block=gate)
    job = client.post("/api/check", json={"text": TEXT}).json()["job"]
    assert client.get(f"/api/job/{job}").json()["state"] == "running"
    # a drawing of the same check is running too
    api._jobs[job].check_id = "c1"
    render = api._add_job(api.Job("render", *api._launch(lambda out: None, ()), check_id="c1"))
    render.proc.block = gate
    assert client.post(f"/api/stop/{job}").json()["state"] == "stopped"
    assert procs[0].terminated and procs[1].terminated
    assert client.get(f"/api/job/{render.id}").json()["state"] == "stopped"
    gate.set()
    assert client.get(f"/api/job/{job}").json()["state"] == "stopped"  # a late answer does not bring it back
    assert client.post("/api/stop/nope").status_code == 404


def test_stop_really_ends_a_worker_process(monkeypatch):
    import time
    client = _client(monkeypatch)
    out = api._CTX.Queue()
    proc = api._CTX.Process(target=time.sleep, args=(60,), daemon=True)
    proc.start()
    monkeypatch.setattr(api, "_launch", lambda target, args: (proc, out))
    job = client.post("/api/check", json={"text": TEXT}).json()["job"]
    assert proc.is_alive()
    assert client.post(f"/api/stop/{job}").json()["state"] == "stopped"
    proc.join(10)
    assert not proc.is_alive()


def test_waiting_check_still_works_for_other_callers(monkeypatch):
    body = _client(monkeypatch).post("/api/check?wait=1", json={"text": TEXT}).json()
    assert body["verdict"]["kind"] == "breaks" and "job" not in body
