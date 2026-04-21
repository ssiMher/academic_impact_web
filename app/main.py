from __future__ import annotations

import json

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.services import impact_core


app = FastAPI(title="Academic Impact Web")
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


def redirect_to_session(session_id: str) -> RedirectResponse:
    return RedirectResponse(url=f"/sessions/{session_id}", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "sessions": impact_core.list_sessions(),
        },
    )


@app.post("/sessions/discover")
async def discover(
    query: str = Form(...),
    limit: int = Form(20),
    probe_downloads: bool = Form(False),
    auto_refresh_top: int = Form(0),
    sort_preference: str = Form("context"),
):
    session_id = impact_core.start_discover_task(
        query=query,
        limit=limit,
        probe_downloads=probe_downloads,
        auto_refresh_top=auto_refresh_top,
        sort_preference=sort_preference,
    )
    return redirect_to_session(session_id)


@app.get("/sessions/{session_id}", response_class=HTMLResponse)
async def session_detail(
    request: Request,
    session_id: str,
    download_status: str = "",
    analysis_status: str = "",
    strong_only: bool = False,
    candidate_only: bool = False,
    page: int = 1,
    page_size: int = 20,
):
    session, status_payload, detail_payload, report_md = impact_core.load_status(
        session_id,
        {
            "download_status": download_status,
            "analysis_status": analysis_status,
            "strong_only": strong_only,
            "candidate_only": candidate_only,
            "page": page,
            "page_size": page_size,
        },
    )
    return templates.TemplateResponse(
        request,
        "session.html",
        {
            "request": request,
            "session_id": session_id,
            "session": session,
            "status_payload": status_payload,
            "detail_payload": detail_payload,
            "status_json": json.dumps(status_payload, ensure_ascii=False, indent=2),
            "report_md": report_md,
        },
    )


@app.post("/sessions/{session_id}/refresh")
async def refresh_session(request: Request, session_id: str):
    form = await request.form()
    ids = form.getlist("paper_ids")
    force = bool(form.get("force"))
    impact_core.start_refresh_task(session_id, ids, force=force)
    return redirect_to_session(session_id)


@app.post("/sessions/{session_id}/download")
async def download_session(request: Request, session_id: str):
    form = await request.form()
    ids = form.getlist("paper_ids")
    auto_only = bool(form.get("auto_only"))
    impact_core.start_download_task(session_id, ids, auto_only=auto_only)
    return redirect_to_session(session_id)


@app.post("/sessions/{session_id}/analyze")
async def analyze_session(
    request: Request,
    session_id: str,
    top_k_spans: int = Form(8),
    analysis_scope: str = Form("fulltext_direct"),
):
    form = await request.form()
    ids = form.getlist("paper_ids")
    impact_core.start_analyze_task(session_id, ids, top_k_spans=top_k_spans, analysis_scope=analysis_scope)
    return redirect_to_session(session_id)


@app.post("/sessions/{session_id}/attach-pdf")
async def attach_pdf(
    session_id: str,
    paper_id: str = Form(...),
    pdf_file: UploadFile = File(...),
):
    filename = pdf_file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="当前只支持上传 PDF 文件。")

    content = await pdf_file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传的 PDF 文件为空。")

    impact_core.attach_uploaded_pdf(session_id, paper_id, filename, content)
    return redirect_to_session(session_id)


@app.post("/sessions/{session_id}/candidates/review")
async def review_candidate(
    session_id: str,
    candidate_id: str = Form(...),
    action: str = Form(...),
    note: str = Form(""),
):
    impact_core.review_person_candidate(session_id, candidate_id, action=action, note=note)
    return redirect_to_session(session_id)


@app.get("/sessions/{session_id}/exports/{export_name}")
async def download_export(session_id: str, export_name: str):
    path = impact_core.resolve_export_path(session_id, export_name)
    media_type = "application/json" if export_name.endswith(".json") else "text/markdown"
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.get("/sessions/{session_id}/task-status")
async def task_status(session_id: str):
    return impact_core.get_task_status(session_id)
