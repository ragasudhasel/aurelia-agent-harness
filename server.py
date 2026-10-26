"""FastAPI Web Control Center and Live Trace API for Render cloud deployment."""

import asyncio
import json
import os
import glob
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.config import load_config
from core.orchestrator import Orchestrator
from benchmarks.evaluate import run_all_benchmarks

app = FastAPI(
    title="Aurelia Task D — Multi-Agent AI Harness Control Center",
    description="Task-agnostic multi-agent orchestration engine with live browser trace visualization.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UI_PATH = os.path.join(BASE_DIR, "ui", "trace_viewer.html")


@app.get("/", response_class=HTMLResponse)
async def serve_trace_viewer():
    """Serve the interactive Trace Viewer UI."""
    if os.path.exists(UI_PATH):
        with open(UI_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h3>Trace Viewer UI not found</h3>", status_code=404)


@app.get("/health")
async def health_check():
    return {"status": "ok", "app": "aurelia-agent-harness", "version": "1.0.0"}


class RunRequest(BaseModel):
    task: str = "reposentinel"  # reposentinel or incidentpilot
    chaos: Optional[str] = None  # None, timeout, or tool_error
    custom_task_prompt: Optional[str] = None


@app.post("/api/run")
async def execute_agent_task(req: RunRequest):
    """Trigger multi-agent orchestration task and return final report."""
    cfg_file = "reposentinel.yaml" if req.task == "reposentinel" else "incidentpilot.yaml"
    cfg_path = os.path.join(BASE_DIR, "configs", cfg_file)

    if not os.path.exists(cfg_path):
        raise HTTPException(status_code=404, detail=f"Config file '{cfg_file}' not found.")

    config = load_config(cfg_path, base_dir=BASE_DIR)

    if req.chaos:
        config.chaos_config.enabled = True
        config.chaos_config.failure_type = req.chaos
        first_agent = list(config.agents.keys())[0]
        config.chaos_config.target_agent = first_agent

    orchestrator = Orchestrator(config=config)
    prompt = req.custom_task_prompt or ("Perform thorough analysis of workspace code and logs.")
    report = await orchestrator.run(user_task=prompt)

    return {
        "status": "success",
        "task_name": config.task_name,
        "run_id": report.run_id,
        "report": report.model_dump(),
        "trace_endpoint": f"/api/trace/{report.run_id}"
    }


@app.get("/api/trace/latest")
async def get_latest_trace():
    """Retrieve the events of the most recent execution trace."""
    runs_dir = os.path.join(BASE_DIR, "runs")
    trace_files = glob.glob(os.path.join(runs_dir, "*", "trace.jsonl"))
    if not trace_files:
        raise HTTPException(status_code=404, detail="No execution traces found yet.")

    latest_file = max(trace_files, key=os.path.getmtime)
    events = []
    with open(latest_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    return {"file": os.path.basename(os.path.dirname(latest_file)), "events": events}


@app.get("/api/trace/{run_id}")
async def get_trace_by_run_id(run_id: str):
    """Retrieve trace events for a specific run ID."""
    trace_file = os.path.join(BASE_DIR, "runs", run_id, "trace.jsonl")
    if not os.path.exists(trace_file):
        raise HTTPException(status_code=404, detail=f"Trace for run '{run_id}' not found.")

    events = []
    with open(trace_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    return {"run_id": run_id, "events": events}


@app.get("/api/benchmarks")
async def execute_benchmarks():
    """Execute all 3 evaluation benchmarks and return metrics."""
    results = await run_all_benchmarks()
    return {"status": "completed", "results": results}
