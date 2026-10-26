"""
FastAPI Live Web Control Center & REST API for Task D (AI-Agent Backend Harness).
Enables seamless cloud deployment on Render with interactive browser UI and Swagger docs.
"""

import os
import glob
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.config import load_config
from core.orchestrator import Orchestrator
from benchmarks.evaluate import run_all_benchmarks

app = FastAPI(
    title="Aurelia Multi-Agent AI Harness",
    description="Task-agnostic, configuration-driven multi-agent orchestration backend with budget enforcement, two-layer output checking, and audit tracing.",
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


@app.get("/health", tags=["Health"])
async def health_check() -> Dict[str, str]:
    return {"status": "healthy", "service": "aurelia-agent-harness"}


@app.post("/api/run/reposentinel", tags=["Execution"])
async def run_reposentinel() -> Dict[str, Any]:
    """Execute repository code review with bug, security, and test specialist agents."""
    cfg_path = os.path.join(BASE_DIR, "configs", "reposentinel.yaml")
    config = load_config(cfg_path, base_dir=BASE_DIR)
    orchestrator = Orchestrator(config=config)
    report = await orchestrator.run(user_task="Perform comprehensive code review of repository A.")
    return report.model_dump()


@app.post("/api/run/incidentpilot", tags=["Execution"])
async def run_incidentpilot() -> Dict[str, Any]:
    """Execute incident log triage with log, incident, and mitigation specialist agents."""
    cfg_path = os.path.join(BASE_DIR, "configs", "incidentpilot.yaml")
    config = load_config(cfg_path, base_dir=BASE_DIR)
    orchestrator = Orchestrator(config=config)
    report = await orchestrator.run(user_task="Investigate cascading database timeout outage from incident logs.")
    return report.model_dump()


@app.post("/api/run/chaos", tags=["Execution"])
async def run_chaos_mode() -> Dict[str, Any]:
    """Demonstrate failure recovery: simulate an agent timeout and verify partial-failure preservation."""
    cfg_path = os.path.join(BASE_DIR, "configs", "reposentinel.yaml")
    config = load_config(cfg_path, base_dir=BASE_DIR)
    config.chaos_config.enabled = True
    config.chaos_config.target_agent = "bug_agent"
    config.chaos_config.failure_type = "timeout"
    orchestrator = Orchestrator(config=config)
    report = await orchestrator.run(user_task="Demonstrate timeout failure recovery on bug_agent.")
    return report.model_dump()


@app.get("/api/benchmark", tags=["Evaluation"])
async def run_benchmarks() -> Dict[str, Any]:
    """Execute full 3-task benchmark comparing Multi-Agent Harness with Single-Agent Baseline."""
    results = await run_all_benchmarks()
    return {"status": "completed", "results": results}


@app.get("/api/runs", tags=["Audit & Tracing"])
async def list_runs() -> Dict[str, Any]:
    """List all available execution trace runs."""
    runs_dir = os.path.join(BASE_DIR, "runs")
    if not os.path.exists(runs_dir):
        return {"runs": []}
    run_folders = [f for f in os.listdir(runs_dir) if os.path.isdir(os.path.join(runs_dir, f))]
    return {"runs": sorted(run_folders, reverse=True)}


@app.get("/api/trace/{run_id}", tags=["Audit & Tracing"])
async def get_trace(run_id: str) -> PlainTextResponse:
    """Retrieve raw JSONL trace lines for a specific run ID."""
    trace_file = os.path.join(BASE_DIR, "runs", run_id, "trace.jsonl")
    if not os.path.exists(trace_file):
        raise HTTPException(status_code=404, detail=f"Trace file not found for run: {run_id}")
    with open(trace_file, "r", encoding="utf-8") as f:
        content = f.read()
    return PlainTextResponse(content=content, media_type="text/plain")


@app.get("/", response_class=HTMLResponse, tags=["Dashboard"])
async def control_center():
    """Live interactive control center for recruiters and evaluators."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Aurelia Multi-Agent AI Harness — Live Control Center</title>
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: rgba(22, 30, 49, 0.75);
      --border: rgba(255, 255, 255, 0.08);
      --accent: #38bdf8;
      --accent-glow: rgba(56, 189, 248, 0.25);
      --text: #f1f5f9;
      --text-muted: #94a3b8;
      --success: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background-color: var(--bg); color: var(--text); padding: 2rem; min-height: 100vh; }
    header { max-width: 1200px; margin: 0 auto 2rem; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 1.5rem; }
    h1 { font-size: 1.75rem; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 0.75rem; }
    .badge { background: var(--accent-glow); color: var(--accent); border: 1px solid var(--accent); padding: 0.25rem 0.75rem; border-radius: 9999px; font-size: 0.8rem; font-weight: 600; }
    .nav-links a { color: var(--accent); text-decoration: none; font-size: 0.95rem; margin-left: 1.5rem; }
    .container { max-width: 1200px; margin: 0 auto; display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }
    .card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; backdrop-filter: blur(10px); }
    .card h2 { font-size: 1.25rem; margin-bottom: 1rem; color: #fff; }
    .button-group { display: flex; flex-direction: column; gap: 0.75rem; margin-bottom: 1.5rem; }
    button { background: #1e293b; color: #fff; border: 1px solid var(--border); padding: 0.85rem 1.25rem; border-radius: 8px; font-size: 0.95rem; font-weight: 600; cursor: pointer; transition: all 0.2s; display: flex; justify-content: space-between; align-items: center; }
    button:hover { background: #334155; border-color: var(--accent); box-shadow: 0 0 15px var(--accent-glow); }
    button.primary { background: linear-gradient(135deg, #0284c7, #2563eb); border: none; }
    button.primary:hover { background: linear-gradient(135deg, #0369a1, #1d4ed8); }
    button.warning { background: linear-gradient(135deg, #b45309, #d97706); border: none; }
    pre { background: #050811; border: 1px solid var(--border); border-radius: 8px; padding: 1rem; color: #38bdf8; font-size: 0.85rem; overflow-x: auto; max-height: 480px; }
    .stat-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin-bottom: 1rem; }
    .stat { background: #0f172a; padding: 1rem; border-radius: 8px; border: 1px solid var(--border); text-align: center; }
    .stat-val { font-size: 1.5rem; font-weight: 700; color: #38bdf8; }
    .stat-lbl { font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; margin-top: 0.25rem; }
    #loader { display: none; color: var(--accent); margin-bottom: 1rem; font-weight: 600; }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Aurelia Multi-Agent AI Harness <span class="badge">Live Control Center</span></h1>
      <p style="color: var(--text-muted); font-size: 0.9rem; margin-top: 0.25rem;">Task-Agnostic, Configuration-Driven Multi-Agent Backend</p>
    </div>
    <div class="nav-links">
      <a href="/docs" target="_blank">Interactive Swagger Docs &rarr;</a>
    </div>
  </header>

  <div class="container">
    <div class="card">
      <h2>Execute Agent Workflows</h2>
      <div id="loader">Running multi-agent orchestration... please wait.</div>
      <div class="button-group">
        <button class="primary" onclick="runTask('/api/run/reposentinel')">
          <span>Run RepoSentinel (Code Review)</span>
          <span>&rarr;</span>
        </button>
        <button onclick="runTask('/api/run/incidentpilot')">
          <span>Run IncidentPilot (Log Triage)</span>
          <span>&rarr;</span>
        </button>
        <button class="warning" onclick="runTask('/api/run/chaos')">
          <span>Run Chaos Mode (Timeout Recovery)</span>
          <span>&rarr;</span>
        </button>
        <button onclick="runTask('/api/benchmark')">
          <span>Run 3-Task Benchmark Suite</span>
          <span>&rarr;</span>
        </button>
      </div>

      <h2>Architecture Guarantees</h2>
      <div class="stat-grid">
        <div class="stat">
          <div class="stat-val">Fail-Closed</div>
          <div class="stat-lbl">Output Checker</div>
        </div>
        <div class="stat">
          <div class="stat-val">5 Limits</div>
          <div class="stat-lbl">Budget Manager</div>
        </div>
        <div class="stat">
          <div class="stat-val">37 / 37</div>
          <div class="stat-lbl">Tests Passing</div>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>Live Execution Output</h2>
      <pre id="output">// Click any button on the left to execute the Multi-Agent Harness live!
// The orchestrator will plan subtasks, coordinate specialists, enforce budgets,
// validate findings with two-layer checking, and stream results here.</pre>
    </div>
  </div>

  <script>
    async function runTask(url) {
      const out = document.getElementById('output');
      const loader = document.getElementById('loader');
      loader.style.display = 'block';
      out.textContent = 'Executing ' + url + '...\\nSpawning Lead Agent & Specialists...';
      try {
        const res = await fetch(url, { method: url.includes('/benchmark') ? 'GET' : 'POST' });
        const data = await res.json();
        out.textContent = JSON.stringify(data, null, 2);
      } catch (err) {
        out.textContent = 'Error executing task: ' + err.message;
      } finally {
        loader.style.display = 'none';
      }
    }
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
