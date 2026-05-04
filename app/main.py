from __future__ import annotations

import json

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.services import impact_core, scholar_core


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


@app.get("/scholars/{session_id}", response_class=HTMLResponse)
async def scholar_detail(
    request: Request,
    session_id: str,
    queue_reason: str = "",
    queue_page: int = 1,
    queue_page_size: int = 20,
):
    try:
        payload = scholar_core.load_scholar_status(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    queue_view = scholar_core.build_deep_analysis_queue_view(
        payload,
        active_reason=queue_reason,
        page=queue_page,
        page_size=queue_page_size,
    )
    analysis_summary = scholar_core.build_scholar_analysis_summary(payload)
    return templates.TemplateResponse(
        request,
        "scholar_session.html",
        {
            "request": request,
            "session_id": session_id,
            "payload": payload,
            "queue_view": queue_view,
            "analysis_summary": analysis_summary,
            "payload_json": json.dumps(payload, ensure_ascii=False, indent=2),
        },
    )


@app.post("/scholars/create")
def create_scholar(
    display_name: str = Form(...),
    dblp_id: str = Form(""),
    openalex_id: str = Form(""),
    scopus_author_id: str = Form(""),
    affiliations: str = Form(""),
):
    normalized_dblp_id = dblp_id.strip()
    if not normalized_dblp_id:
        raise HTTPException(status_code=400, detail="创建学者会话需要 DBLP ID")
    author = {
        "display_name": display_name.strip(),
        "dblp_id": normalized_dblp_id,
        "openalex_id": openalex_id.strip(),
        "scopus_author_id": scopus_author_id.strip(),
        "affiliations": [item.strip() for item in affiliations.split("|") if item.strip()],
    }
    session_id = scholar_core.create_scholar_session(author)
    return RedirectResponse(url=f"/scholars/{session_id}", status_code=303)


@app.post("/scholars/{session_id}/expand-citations")
def expand_scholar_citations(
    session_id: str,
    limit_per_publication: int = Form(100),
):
    if limit_per_publication < 1 or limit_per_publication > 200:
        raise HTTPException(status_code=400, detail="每篇论文最多引用数必须在 1 到 200 之间")
    try:
        scholar_core.start_expand_citations_task(
            session_id,
            limit_per_publication=limit_per_publication,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(url=f"/scholars/{session_id}", status_code=303)


@app.post("/scholars/{session_id}/rebuild-derived")
def rebuild_scholar_derived_outputs(
    session_id: str,
    queue_limit: int = Form(300),
):
    if queue_limit < 1 or queue_limit > 1000:
        raise HTTPException(status_code=400, detail="高价值队列上限必须在 1 到 1000 之间")
    try:
        scholar_core.rebuild_scholar_derived_outputs(
            session_id,
            queue_limit=queue_limit,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RedirectResponse(
        url=f"/scholars/{session_id}#deep-analysis-queue",
        status_code=303,
    )


@app.post("/scholars/{session_id}/analyze-queue")
async def analyze_scholar_queue(
    request: Request,
    session_id: str,
    top_k_spans: int = Form(8),
    analysis_scope: str = Form("fulltext_direct"),
):
    form = await request.form()
    queue_ids = [
        str(item).strip()
        for item in form.getlist("queue_ids")
        if str(item).strip()
    ]
    if not queue_ids:
        raise HTTPException(status_code=400, detail="请先选择要分析的高价值引用论文")
    if top_k_spans < 1 or top_k_spans > 20:
        raise HTTPException(status_code=400, detail="候选段落数必须在 1 到 20 之间")
    try:
        scholar_core.start_analyze_queue_task(
            session_id,
            queue_ids=queue_ids,
            top_k_spans=top_k_spans,
            analysis_scope=analysis_scope,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(url=f"/scholars/{session_id}", status_code=303)


@app.get("/scholars/{session_id}/task-status")
def scholar_task_status(session_id: str):
    try:
        return scholar_core.get_scholar_task_status(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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

    try:
        impact_core.attach_uploaded_pdf(session_id, paper_id, filename, content)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
