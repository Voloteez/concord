"""FastAPI app: serves frontend/ at "/" and the API under /api. See CONTRACT.md."""
from __future__ import annotations

import asyncio
import datetime as _dt
import html
import json
import os
import secrets
import shutil
import threading

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

import extract
import pipeline

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Serverless (Vercel): the bundle is read-only and there is no background thread that
# outlives the request, so runs live in /tmp and the pipeline runs inside the POST.
SERVERLESS = bool(os.environ.get("VERCEL") or os.environ.get("CONCORD_SYNC"))
RUNS_DIR = os.path.join("/tmp", "concord", "runs") if SERVERLESS else os.path.join(BASE_DIR, "data", "runs")
pipeline.RUNS_DIR = RUNS_DIR
SAMPLE_DIR = os.path.join(BASE_DIR, "data", "sample")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
os.makedirs(RUNS_DIR, exist_ok=True)
if SERVERLESS:
    os.environ.setdefault("CONCORD_MIN_STAGE_S", "0")

STATUSES = {"unreviewed", "confirmed", "dismissed", "unresolved"}
DISMISS_REASONS = {"false_positive", "acceptable_variation", "will_fix_in_source"}
ZERO_COUNTS = {"critical": 0, "material": 0, "cosmetic": 0, "unaligned_sections": 0, "reviewed": 0, "total": 0}

app = FastAPI(title="Concord")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ApiError(Exception):
    def __init__(self, status: int, msg: str):
        self.status, self.msg = status, msg


@app.exception_handler(ApiError)
async def _api_error(_: Request, e: ApiError):
    return JSONResponse({"error": e.msg}, status_code=e.status)


@app.exception_handler(Exception)
async def _any_error(_: Request, e: Exception):
    return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


# ---------------------------------------------------------------- run registry

class RunState:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.events: list[dict] = []
        self.cond = threading.Condition()
        self.finished = False
        self.lock = threading.Lock()  # guards findings.json read-modify-write

    def push(self, ev: dict):
        with self.cond:
            self.events.append(ev)
            if ev.get("stage") == "done" and ev.get("done"):
                self.finished = True
            self.cond.notify_all()


_runs: dict[str, RunState] = {}
_runs_lock = threading.Lock()


def _state(run_id: str, create: bool = False) -> RunState | None:
    with _runs_lock:
        st = _runs.get(run_id)
        if st is None and create:
            st = _runs[run_id] = RunState(run_id)
        return st


def _run_dir(run_id: str) -> str:
    if not run_id or "/" in run_id or ".." in run_id:
        raise ApiError(400, "bad run id")
    rd = os.path.join(RUNS_DIR, run_id)
    if not os.path.isdir(rd):
        raise ApiError(404, f"run {run_id} not found")
    return rd


def _read_json(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _start(run_id: str, authoritative: str | None) -> None:
    rd = os.path.join(RUNS_DIR, run_id)
    _write_json(os.path.join(rd, "meta.json"), {
        "run_id": run_id,
        "authoritative": authoritative,
        "created_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    st = _state(run_id, create=True)

    def on_progress(stage, label, done=False, detail=None):
        ev = {"stage": stage, "label": label, "done": bool(done)}
        if detail is not None:
            ev["detail"] = detail
        st.push(ev)

    if SERVERLESS:
        return None  # caller runs it inline via _run_sync
    threading.Thread(target=pipeline.run_pipeline, args=(run_id, on_progress), daemon=True,
                     name=f"pipeline-{run_id}").start()


async def _run_sync(run_id: str, sample: bool = False) -> dict:
    """Serverless: run the whole pipeline inside the request and return the run object."""
    st = _state(run_id, create=True)

    def on_progress(stage, label, done=False, detail=None):
        st.push({"stage": stage, "label": label, "done": bool(done), "detail": detail})

    await asyncio.to_thread(pipeline.run_pipeline, run_id, on_progress)
    run = _load_run(run_id)
    run["sample"] = sample
    run["local"] = True  # tells the frontend to keep this run client-side
    return run


def _new_run_id() -> str:
    while True:
        rid = "r_" + secrets.token_hex(2)
        if not os.path.exists(os.path.join(RUNS_DIR, rid)):
            return rid


def _norm_auth(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if v.upper() in ("EN", "ZH"):
        return v.upper()
    if v.lower() in ("none", "neither", ""):
        return "none" if v else None
    raise ApiError(400, "authoritative must be EN, ZH or none")


# ---------------------------------------------------------------- endpoints

@app.get("/api/health")
async def health():
    return {"ok": True}


@app.post("/api/runs")
async def create_run(en: UploadFile = File(...), zh: UploadFile = File(...),
                     authoritative: str | None = Form(None)):
    auth = _norm_auth(authoritative)
    rid = _new_run_id()
    rd = os.path.join(RUNS_DIR, rid)
    os.makedirs(rd, exist_ok=True)
    for up, name in ((en, "en.pdf"), (zh, "zh.pdf")):
        data = await up.read()
        if not data:
            shutil.rmtree(rd, ignore_errors=True)
            raise ApiError(400, f"empty upload for {name[:2]}")
        if not data[:5].startswith(b"%PDF"):
            shutil.rmtree(rd, ignore_errors=True)
            raise ApiError(400, f"{up.filename or name} is not a PDF")
        with open(os.path.join(rd, name), "wb") as f:
            f.write(data)
    _start(rid, auth)
    if SERVERLESS:
        return await _run_sync(rid)
    return {"run_id": rid}


@app.post("/api/runs/sample")
async def create_sample_run():
    src_en, src_zh = os.path.join(SAMPLE_DIR, "en.pdf"), os.path.join(SAMPLE_DIR, "zh.pdf")
    if not (os.path.exists(src_en) and os.path.exists(src_zh)):
        raise ApiError(404, "sample pair not found in data/sample/")
    rid = _new_run_id()
    rd = os.path.join(RUNS_DIR, rid)
    os.makedirs(rd, exist_ok=True)
    shutil.copyfile(src_en, os.path.join(rd, "en.pdf"))
    shutil.copyfile(src_zh, os.path.join(rd, "zh.pdf"))
    _start(rid, None)
    if SERVERLESS:
        return await _run_sync(rid, sample=True)
    return {"run_id": rid}


def _load_run(run_id: str) -> dict:
    rd = _run_dir(run_id)
    run = _read_json(os.path.join(rd, "findings.json"))
    if run is None:
        meta = _read_json(os.path.join(rd, "meta.json"), {}) or {}
        run = {"run_id": run_id, "status": "running", "created_at": meta.get("created_at"),
               "meta": {}, "counts": dict(ZERO_COUNTS), "findings": [], "unaligned_sections": [], "glossary": []}
    return run


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    return _load_run(run_id)


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, request: Request):
    rd = _run_dir(run_id)
    st = _state(run_id, create=True)
    # Server restarted after the run finished: synthesize the terminal event.
    if not st.events and os.path.exists(os.path.join(rd, "findings.json")):
        run = _read_json(os.path.join(rd, "findings.json"), {}) or {}
        st.push({"stage": "done", "label": "Done" if run.get("status") == "done" else run.get("error", "Error"),
                 "done": True, "detail": {"counts": run.get("counts", {})}})

    async def gen():
        i = 0
        while True:
            if await request.is_disconnected():
                return
            with st.cond:
                batch = st.events[i:]
                i = len(st.events)
                finished = st.finished
            for ev in batch:
                yield {"data": json.dumps(ev, ensure_ascii=False)}
                if ev.get("stage") == "done" and ev.get("done"):
                    return
            if finished:
                return
            # wait for new events, heartbeat every 15 s
            got = await asyncio.to_thread(_wait_for_events, st, i, 15.0)
            if not got:
                yield {"comment": "heartbeat"}

    return EventSourceResponse(gen(), ping=15)


def _wait_for_events(st: RunState, seen: int, timeout: float) -> bool:
    with st.cond:
        if len(st.events) > seen:
            return True
        st.cond.wait(timeout)
        return len(st.events) > seen


@app.patch("/api/runs/{run_id}/findings/{fid}")
async def patch_finding(run_id: str, fid: str, request: Request):
    rd = _run_dir(run_id)
    try:
        body = await request.json()
    except Exception:
        raise ApiError(400, "body must be JSON")
    if not isinstance(body, dict):
        raise ApiError(400, "body must be a JSON object")
    st = _state(run_id, create=True)
    with st.lock:
        path = os.path.join(rd, "findings.json")
        run = _read_json(path)
        if run is None:
            raise ApiError(409, "run is still processing")
        finding = next((f for f in run.get("findings", []) if f.get("id") == fid), None)
        if finding is None:
            raise ApiError(404, f"finding {fid} not found")
        new_status = body.get("status", finding.get("status"))
        if new_status not in STATUSES:
            raise ApiError(400, f"status must be one of {sorted(STATUSES)}")
        new_reason = body.get("dismiss_reason", finding.get("dismiss_reason")) if "dismiss_reason" in body \
            else (finding.get("dismiss_reason") if new_status == "dismissed" else None)
        if new_reason is not None and new_reason not in DISMISS_REASONS:
            raise ApiError(400, f"dismiss_reason must be one of {sorted(DISMISS_REASONS)}")
        if new_status == "dismissed" and not new_reason:
            raise ApiError(400, "dismiss_reason is required when status is dismissed")
        if new_status != "dismissed":
            new_reason = None
        finding["status"] = new_status
        finding["dismiss_reason"] = new_reason
        if "note" in body:
            note = body.get("note")
            if note is not None and not isinstance(note, str):
                raise ApiError(400, "note must be a string or null")
            finding["note"] = note or None
        run["counts"] = pipeline.recount(run["findings"], run.get("unaligned_sections", []))
        _write_json(path, run)
    return finding


@app.get("/api/runs/{run_id}/page/{lang}/{n}.png")
async def page_png(run_id: str, lang: str, n: int):
    rd = _run_dir(run_id)
    if lang not in ("en", "zh"):
        raise ApiError(400, "lang must be en or zh")
    out = os.path.join(rd, "pages", f"{lang}_{n}.png")
    if not os.path.exists(out):
        try:
            await asyncio.to_thread(extract.render_page_png, os.path.join(rd, f"{lang}.pdf"), n, out, 1.5)
        except ValueError as e:
            raise ApiError(404, str(e))
    return FileResponse(out, media_type="image/png", headers={"Cache-Control": "max-age=3600"})


def _fallback_report(run: dict) -> str:
    m = run.get("meta", {})
    rows = "".join(
        f"<tr><td>{html.escape(f.get('id',''))}</td><td>{html.escape(f.get('severity',''))}</td>"
        f"<td>{html.escape(f.get('type',''))}</td><td>{html.escape(f.get('section') or '')}</td>"
        f"<td>{html.escape((f.get('en') or {}).get('text') or '')}</td>"
        f"<td lang=\"zh\">{html.escape((f.get('zh') or {}).get('text') or '')}</td>"
        f"<td>{html.escape(f.get('explanation') or '')}</td><td>{html.escape(f.get('status',''))}</td></tr>"
        for f in run.get("findings", []))
    c = run.get("counts", {})
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Concord report {html.escape(run.get('run_id',''))}</title>
<style>body{{font-family:system-ui,sans-serif;color:#181925;margin:40px}}table{{border-collapse:collapse;width:100%;font-size:12px}}
td,th{{border-bottom:1px solid #e8e8e8;padding:6px;vertical-align:top;text-align:left}}h1{{letter-spacing:-0.02em}}</style></head><body>
<h1>Consistency sign-off report</h1><p>{html.escape(m.get('en_title') or '')}<br>{html.escape(m.get('zh_title') or '')}</p>
<p>{html.escape(m.get('company') or '')} {html.escape(m.get('stock_code') or '')} · authoritative: {html.escape(str(m.get('authoritative')))}
· Critical {c.get('critical',0)} · Material {c.get('material',0)} · Cosmetic {c.get('cosmetic',0)} · reviewed {c.get('reviewed',0)}/{c.get('total',0)}</p>
<table><tr><th>ID</th><th>Severity</th><th>Type</th><th>Section</th><th>EN</th><th>ZH</th><th>Explanation</th><th>Status</th></tr>{rows}</table>
</body></html>"""


@app.get("/api/runs/{run_id}/report")
async def run_report(run_id: str):
    run = _load_run(run_id)
    if run.get("status") == "running":
        raise ApiError(409, "run is still processing")
    try:
        import report
        html_out = report.render_report(run)
    except Exception as e:
        print(f"[api] report.render_report unavailable: {e}")
        html_out = _fallback_report(run)
    return HTMLResponse(html_out)


@app.post("/api/report")
async def report_from_body(request: Request):
    """Render the sign-off report for a run object the client holds (serverless mode)."""
    try:
        run = await request.json()
    except Exception:
        raise ApiError(400, "body must be the run JSON")
    if not isinstance(run, dict) or "findings" not in run:
        raise ApiError(400, "body must be a run object")
    try:
        import report
        return HTMLResponse(report.render_report(run))
    except Exception as e:
        print(f"[api] report.render_report unavailable: {e}")
        return HTMLResponse(_fallback_report(run))


@app.get("/api/sample/page/{lang}/{n}.png")
async def sample_page_png(lang: str, n: int):
    if lang not in ("en", "zh"):
        raise ApiError(400, "lang must be en or zh")
    out = os.path.join("/tmp", "concord", "sample_pages", f"{lang}_{n}.png")
    if not os.path.exists(out):
        try:
            await asyncio.to_thread(extract.render_page_png, os.path.join(SAMPLE_DIR, f"{lang}.pdf"), n, out, 1.5)
        except ValueError as e:
            raise ApiError(404, str(e))
    return FileResponse(out, media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@app.get("/api/runs/{run_id}/export.json")
async def run_export(run_id: str):
    run = _load_run(run_id)
    return JSONResponse(run, headers={"Content-Disposition": f'attachment; filename="concord_{run_id}.json"'})


# ---------------------------------------------------------------- frontend

PLACEHOLDER = """<!doctype html><html><head><meta charset="utf-8"><title>Concord</title></head>
<body style="font-family:system-ui;margin:40px;color:#181925"><h1 style="letter-spacing:-0.02em">Concord</h1>
<p>Frontend not built yet. API is live: <a href="/api/health">/api/health</a>.</p></body></html>"""


@app.get("/{path:path}", include_in_schema=False)
async def frontend(path: str):
    if path.startswith("api/"):
        raise ApiError(404, "not found")
    if path:
        candidate = os.path.abspath(os.path.join(FRONTEND_DIR, path))
        if candidate.startswith(os.path.abspath(FRONTEND_DIR) + os.sep) and os.path.isfile(candidate):
            return FileResponse(candidate)
    index = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.isfile(index):
        return FileResponse(index, media_type="text/html")
    return HTMLResponse(PLACEHOLDER)
