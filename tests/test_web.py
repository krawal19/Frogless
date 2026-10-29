"""The web page and API, with the checker and the drawing mocked: no model calls, no browser."""

from fastapi.testclient import TestClient

from frogless.patterns.terms import Terms
from frogless.pipeline.report import Fix, PatternReport, RowResult, Verdict
from frogless.web import api, ui

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
    res = client.post("/api/check", json={"text": TEXT, "terms": "UK"})
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
    body = _client(monkeypatch).post("/api/check", json={"text": TEXT}).json()
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
    body = client.post("/api/check", json={"text": TEXT}).json()
    assert body["corrected_status"] == "no_fix" and body["corrected_pattern"] is None
    assert client.post("/api/check", json={"text": "  "}).status_code == 400
    assert client.post("/api/check", json={"text": TEXT, "terms": "French"}).status_code == 422


def test_render_serves_images_from_logs_web(monkeypatch, tmp_path):
    client = _client(monkeypatch)
    monkeypatch.setattr(api, "WEB_DIR", tmp_path)
    client = TestClient(api.create_api())
    monkeypatch.setattr("frogless.pipeline.check.check_pattern", lambda text, **kw: _report())
    check_id = client.post("/api/check", json={"text": TEXT}).json()["id"]

    def fake_chart(report, out_dir, name):
        out_dir.mkdir(parents=True, exist_ok=True)
        sym, sk = out_dir / f"{name}_symbols.png", out_dir / f"{name}_connectivity.png"
        sym.write_bytes(b"png"), sk.write_bytes(b"png")
        return {"chart": str(sym), "symbols": str(sym), "connectivity": str(sk), "overlay": None, "view": None,
                "error": None, "note": "", "kind": "chart"}

    monkeypatch.setattr(api.output, "written_chart", fake_chart)
    monkeypatch.setattr(api.output, "corrected_chart", fake_chart)
    res = client.post(f"/api/render/{check_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["written"]["symbols"] == f"/files/{check_id}/size0/written_symbols.png"
    assert body["corrected"]["sketch"] == f"/files/{check_id}/size0/corrected_connectivity.png"
    assert body["render_seconds"] >= 0
    assert client.get(body["written"]["symbols"]).content == b"png"
    assert client.post("/api/render/nope").status_code == 404


def test_multi_size_gives_one_result_per_size(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr("frogless.pipeline.check.check_pattern_sizes",
                        lambda text, **kw: [("Small", _report()), ("Large", _report(False))])
    body = client.post("/api/check", json={"text": TEXT}).json()
    assert [r["label"] for r in body["results"]] == ["Small", "Large"]
    assert body["results"][1]["corrected_status"] == "no_fix"
    assert body["cost_usd"] == 0.0246


def test_ui_builds_and_html_pieces(monkeypatch):
    assert ui.build_ui() is not None
    body = _client(monkeypatch).post("/api/check", json={"text": TEXT}).json()
    assert "banner breaks" in ui.banner_html(body)
    assert "pl breaks" in ui.left_html(body) and "pl fix" in ui.right_html(body)
    assert "No re-checked fix found" in ui.right_html({**body, "corrected_status": "no_fix"})
    assert "No corrections needed" in ui.right_html({**body, "corrected_status": "none_needed"})
    images = {"symbols": "/files/x/a.png", "sketch": "/files/x/b.png", "view_3d": None, "error": None, "note": ""}
    assert "/files/x/b.png" in ui.chart_html(images, "Sketch") and "3D" not in ui.view_choices(images)
    assert "render charts" in ui.details_html(body, 1.2, 0.0123)
    assert "<script" not in ui.banner_html({**body, "user_message": "<script>x</script>"})


def test_fix_that_cannot_be_placed_shows_the_rebuilt_pattern(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(api.output, "corrected_pattern", lambda r: None)
    monkeypatch.setattr(api.output, "clean_pattern", lambda r: "Round 1: sc 6. (6)\nRound 2: sc 12. (12) [suggested fix: x]")
    body = client.post("/api/check", json={"text": TEXT}).json()
    assert body["corrected_pattern"] is None and body["corrected_source"] == "rebuilt"
    assert [line["mark"] for line in body["corrected_lines"]] == ["", "fix"]
    assert "rebuilt" in ui.right_html(body)
