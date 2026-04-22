"""workflows router — list workflows, trigger runs, read pipeline status.

Phase 4: real surface for POST /api/workflows/{id}/run. The engine today
runs ``filter_universe`` for real and stubs the other step kinds — enough
to demo the end-to-end plumbing from UI → engine → file outputs.

Routes
------
GET  /api/workflows             → list all workflows (id, description, schedule)
GET  /api/workflows/{id}        → full parsed workflow (for preview / editor)
POST /api/workflows/{id}/run    → trigger a workflow; returns WorkflowRunResult
GET  /api/pipeline/status       → read data/pipeline_status.json
GET  /api/universe/latest       → read data/universe_latest.json
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from services import pipeline_service
from services.settings_service import Settings, get_settings
from services.workflow_engine import (
    PIPELINE_STATUS_FILE,
    UNIVERSE_LATEST_FILE,
    WorkflowEngine,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _engine(s: Settings = Depends(get_settings)) -> WorkflowEngine:
    return WorkflowEngine(s)


@router.get("/api/workflows")
async def list_workflows(engine: WorkflowEngine = Depends(_engine)) -> dict:
    workflows = await engine.list_workflows()
    return {
        "workflows": [
            {
                "workflow_id": w.workflow_id,
                "description": w.description,
                "default_mode": w.default_mode,
                "schedule": w.schedule,
                "step_count": len(w.steps),
                "steps": [
                    {"id": s.id, "kind": s.kind, "depends_on": s.depends_on}
                    for s in w.steps
                ],
            }
            for w in workflows
        ]
    }


@router.get("/api/workflows/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    engine: WorkflowEngine = Depends(_engine),
) -> dict:
    try:
        wf = await engine.load_by_id(workflow_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return wf.model_dump()


@router.post("/api/workflows/{workflow_id}/run")
async def run_workflow(
    workflow_id: str,
    mode: str | None = Query(default=None),
    s: Settings = Depends(get_settings),
) -> dict:
    """Production workflow run: engine + compliance/risk gates + DB persist.

    Returns a summary dict; individual plans (with verdicts) land in the
    pending_approvals SQLite table for the ``/pending`` page to read.
    """
    try:
        return await pipeline_service.run_workflow_by_id(
            workflow_id, mode=mode, settings=s,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/api/pipeline/status")
async def pipeline_status() -> dict:
    if not PIPELINE_STATUS_FILE.exists():
        return {"status": "never_run"}
    try:
        return json.loads(PIPELINE_STATUS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "error", "detail": "pipeline_status.json unreadable"}


@router.get("/api/pipeline/runs")
async def pipeline_runs(limit: int = 20) -> dict:
    runs = await pipeline_service.list_runs(limit=limit)
    return {"runs": runs}


@router.get("/api/universe/latest")
async def universe_latest() -> dict:
    if not UNIVERSE_LATEST_FILE.exists():
        return {"status": "never_run"}
    try:
        return json.loads(UNIVERSE_LATEST_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500, detail="universe_latest.json unreadable",
        )
