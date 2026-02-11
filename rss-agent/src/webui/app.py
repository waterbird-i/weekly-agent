"""FastAPI app for RSS Agent visual dashboard."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .runner import RunManager, RunRequest
from .storage import RunStorage, TERMINAL_STATUSES

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]  # rss-agent/
DB_PATH = PROJECT_ROOT / "cache" / "webui_runs.db"

storage = RunStorage(DB_PATH)
manager = RunManager(project_root=PROJECT_ROOT, python_exec=os.environ.get("PYTHON_EXECUTABLE", "python"), storage=storage)

app = FastAPI(title="RSS Agent Dashboard", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(MODULE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(MODULE_DIR / "templates"))


class StartRunPayload(BaseModel):
    """Payload for starting a run."""

    mode: str = "weekly"
    dry_run: bool = False
    config_path: str = "config/config.yaml"
    weekly_config_path: str = "config/weekly_config.yaml"
    max_articles: Optional[int] = None
    hours: Optional[int] = None
    extra_args: List[str] = Field(default_factory=list)


def _resolve_artifact_path(path_text: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = PROJECT_ROOT / path

    resolved = path.resolve()
    project_root = PROJECT_ROOT.resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="产物路径超出项目目录") from exc
    return resolved


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main dashboard page."""
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "project_root": str(PROJECT_ROOT),
        },
    )


@app.get("/api/runs")
def list_runs(limit: int = Query(default=100, ge=1, le=500)):
    """List recent runs."""
    return {"runs": storage.list_runs(limit=limit)}


@app.get("/api/runs/{run_id}")
def get_run(run_id: int):
    """Get one run details."""
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return {"run": run}


@app.get("/api/runs/{run_id}/logs")
def get_run_logs(
    run_id: int,
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
):
    """Get logs for a run."""
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return {"logs": storage.get_logs(run_id, after_id=after_id, limit=limit)}


@app.post("/api/runs")
def start_run(payload: StartRunPayload):
    """Start a new run."""
    mode = payload.mode.strip().lower()
    if mode not in {"weekly", "standard"}:
        raise HTTPException(status_code=400, detail="mode 仅支持 weekly 或 standard")

    request = RunRequest(
        mode=mode,
        dry_run=payload.dry_run,
        config_path=payload.config_path.strip() or "config/config.yaml",
        weekly_config_path=payload.weekly_config_path.strip() or "config/weekly_config.yaml",
        max_articles=payload.max_articles,
        hours=payload.hours,
        extra_args=[arg.strip() for arg in payload.extra_args if arg.strip()],
    )

    stats_seed = {
        "requested_mode": request.mode,
        "requested_dry_run": request.dry_run,
    }
    if request.max_articles is not None:
        stats_seed["requested_max_articles"] = request.max_articles
    if request.hours is not None:
        stats_seed["requested_hours"] = request.hours

    try:
        run_id = manager.start_run(request)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    storage.merge_stats(run_id, stats_seed)
    run = storage.get_run(run_id)
    return {"run_id": run_id, "run": run}


@app.post("/api/runs/{run_id}/rerun")
def rerun(run_id: int):
    """Rerun from an existing run configuration."""
    try:
        new_run_id = manager.rerun(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {
        "run_id": new_run_id,
        "run": storage.get_run(new_run_id),
    }


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: int, delete_artifact: bool = Query(default=False)):
    """Delete run record and optionally its artifact file."""
    deleted, artifact_deleted = storage.delete_run(run_id, delete_artifact=delete_artifact)
    if not deleted:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return {
        "deleted": True,
        "artifact_deleted": artifact_deleted,
    }


@app.get("/api/runs/{run_id}/artifact")
def get_artifact(run_id: int):
    """Load markdown artifact content for preview."""
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")

    output_path = run.get("output_path")
    if not output_path:
        raise HTTPException(status_code=404, detail="该运行没有产物路径")

    path = _resolve_artifact_path(output_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="产物文件不存在")

    content = path.read_text(encoding="utf-8", errors="ignore")
    max_chars = 120000
    truncated = len(content) > max_chars

    return {
        "path": str(path),
        "content": content[:max_chars],
        "truncated": truncated,
    }


@app.get("/api/runs/{run_id}/events")
async def stream_events(run_id: int, request: Request):
    """SSE stream for run logs and status changes."""
    if not storage.get_run(run_id):
        raise HTTPException(status_code=404, detail="运行记录不存在")

    async def event_generator():
        last_log_id = 0
        last_run_fingerprint = ""
        yield "retry: 2000\n\n"

        while True:
            if await request.is_disconnected():
                break

            run = storage.get_run(run_id)
            if not run:
                payload = {"type": "deleted", "data": {"run_id": run_id}}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                break

            logs = storage.get_logs(run_id, after_id=last_log_id, limit=500)
            for log in logs:
                last_log_id = log["id"]
                payload = {"type": "log", "data": log}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            fingerprint = json.dumps(
                {
                    "status": run.get("status"),
                    "progress": run.get("progress"),
                    "current_step": run.get("current_step"),
                    "updated_at": run.get("updated_at"),
                    "output_path": run.get("output_path"),
                },
                ensure_ascii=False,
                sort_keys=True,
            )

            if fingerprint != last_run_fingerprint:
                last_run_fingerprint = fingerprint
                payload = {"type": "run", "data": run}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            if run.get("status") in TERMINAL_STATUSES and not logs:
                payload = {
                    "type": "done",
                    "data": {"run_id": run_id, "status": run.get("status")},
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                break

            yield ": ping\n\n"
            await asyncio.sleep(1)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)
