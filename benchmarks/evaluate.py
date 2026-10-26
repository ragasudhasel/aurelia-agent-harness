"""Benchmark evaluation engine comparing Multi-Agent Harness with Single-Agent Baseline across 3 tasks."""

import asyncio
import json
import os
import time
from typing import Dict, Any, List, Tuple
from core.config import load_config
from core.orchestrator import Orchestrator
from core.schemas import FinalReport, Finding
from agents.baseline import BaselineAgent
from tools.security_guard import ToolRegistry


def score_findings(
    reported: List[Finding],
    ground_truth_findings: List[Dict[str, Any]]
) -> Tuple[float, float, float]:
    """
    Calculate Precision, Recall, and F1 score between reported findings and ground truth.
    A match occurs when category matches and any title keyword is present.
    """
    if not ground_truth_findings:
        return 1.0, 1.0, 1.0

    true_positives = 0
    matched_gt = set()

    for r in reported:
        match_found = False
        for idx, gt in enumerate(ground_truth_findings):
            if idx in matched_gt:
                continue
            cat_match = r.category.lower() == gt.get("category", "").lower()
            keywords = gt.get("title_keywords", [])
            text_to_search = (r.title + " " + r.description).lower()
            keyword_match = any(kw.lower() in text_to_search for kw in keywords)

            if cat_match and keyword_match:
                true_positives += 1
                matched_gt.add(idx)
                match_found = True
                break

    precision = true_positives / len(reported) if reported else 0.0
    recall = true_positives / len(ground_truth_findings) if ground_truth_findings else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    return round(precision, 3), round(recall, 3), round(f1, 3)


def score_incident_root_cause(
    reported: List[Finding],
    ground_truth_root: Dict[str, Any]
) -> bool:
    """Verify if reported findings successfully isolate the ground-truth root cause."""
    keywords = ground_truth_root.get("trigger_keywords", [])
    for r in reported:
        text = (r.title + " " + r.description).lower()
        if any(kw.lower() in text for kw in keywords):
            return True
    return False


async def run_benchmark_task(
    config_path: str,
    ground_truth_path: str,
    user_task: str,
    task_id: str
) -> Dict[str, Any]:
    """Execute benchmark task for both Multi-Agent and Baseline agents."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = load_config(config_path, base_dir=base_dir)

    with open(ground_truth_path, "r", encoding="utf-8") as f:
        gt_data = json.load(f)

    safe_id = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in task_id)
    # 1. Multi-Agent Run
    multi_orchestrator = Orchestrator(config=config)
    t0 = time.monotonic()
    multi_report: FinalReport = await multi_orchestrator.run(user_task=user_task, run_id=f"bm_multi_{safe_id}")
    multi_duration = time.monotonic() - t0

    # 2. Baseline Run
    baseline_agent = BaselineAgent(
        workspace_root=config.workspace_root,
        tool_registry=multi_orchestrator.tool_registry,
        model_client=multi_orchestrator.model_client
    )
    t1 = time.monotonic()
    base_report: FinalReport = await baseline_agent.run(user_task=user_task, run_id=f"bm_base_{safe_id}")
    base_duration = time.monotonic() - t1

    # Score Results
    if "expected_findings" in gt_data:
        m_prec, m_rec, m_f1 = score_findings(multi_report.verified_findings, gt_data["expected_findings"])
        b_prec, b_rec, b_f1 = score_findings(base_report.verified_findings, gt_data["expected_findings"])
    else:
        # Incident root cause evaluation
        m_correct = score_incident_root_cause(multi_report.verified_findings, gt_data["expected_root_cause"])
        b_correct = score_incident_root_cause(base_report.verified_findings, gt_data["expected_root_cause"])
        m_prec, m_rec, m_f1 = (1.0 if m_correct else 0.0), (1.0 if m_correct else 0.0), (1.0 if m_correct else 0.0)
        b_prec, b_rec, b_f1 = (1.0 if b_correct else 0.0), (1.0 if b_correct else 0.0), (1.0 if b_correct else 0.0)

    return {
        "task_id": task_id,
        "multi_agent": {
            "status": multi_report.overall_status.value,
            "duration_sec": round(multi_duration, 3),
            "findings_count": len(multi_report.verified_findings),
            "precision": m_prec,
            "recall": m_rec,
            "f1": m_f1,
            "tool_calls": multi_report.metrics.tool_calls,
            "retries": multi_report.metrics.retries_count,
            "failures": len(multi_report.partial_failures),
        },
        "single_agent_baseline": {
            "status": base_report.overall_status.value,
            "duration_sec": round(base_duration, 3),
            "findings_count": len(base_report.verified_findings),
            "precision": b_prec,
            "recall": b_rec,
            "f1": b_f1,
            "tool_calls": base_report.metrics.tool_calls,
            "retries": 0,
            "failures": len(base_report.partial_failures),
        }
    }


async def run_all_benchmarks() -> List[Dict[str, Any]]:
    """Run all three benchmark suites and output tabular results."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    suite = [
        (
            os.path.join(root, "configs", "reposentinel.yaml"),
            os.path.join(root, "benchmarks", "ground_truth", "repo_a.json"),
            "Perform comprehensive code review of repository A.",
            "Task-1: Repo A Code Review"
        ),
        (
            os.path.join(root, "configs", "reposentinel.yaml"),
            os.path.join(root, "benchmarks", "ground_truth", "repo_b.json"),
            "Audit authentication and security controls in repository B.",
            "Task-2: Repo B Security Audit"
        ),
        (
            os.path.join(root, "configs", "incidentpilot.yaml"),
            os.path.join(root, "benchmarks", "ground_truth", "incident_logs.json"),
            "Investigate cascading database timeout outage from incident logs.",
            "Task-3: Incident Log Triage"
        )
    ]

    results = []
    print("\n" + "=" * 90)
    print("TASK D: MULTI-AGENT HARNESS VS SINGLE-AGENT BASELINE BENCHMARK SUITE")
    print("=" * 90)

    for cfg, gt, prompt, title in suite:
        print(f"\nExecuting Benchmark: {title}...")
        res = await run_benchmark_task(cfg, gt, prompt, title)
        results.append(res)

        m = res["multi_agent"]
        b = res["single_agent_baseline"]
        print(f"  [Multi-Agent]  Precision: {m['precision']:.2f} | Recall: {m['recall']:.2f} | F1: {m['f1']:.2f} | Time: {m['duration_sec']}s | Tools: {m['tool_calls']}")
        print(f"  [Baseline]     Precision: {b['precision']:.2f} | Recall: {b['recall']:.2f} | F1: {b['f1']:.2f} | Time: {b['duration_sec']}s | Tools: {b['tool_calls']}")

    print("\n" + "=" * 90)
    print("BENCHMARK SUMMARY TABLE")
    print("=" * 90)
    print(f"{'Benchmark Task':<32} | {'Approach':<14} | {'F1':<6} | {'Precision':<10} | {'Recall':<8} | {'Time (s)':<8}")
    print("-" * 90)
    for r in results:
        t = r["task_id"]
        m = r["multi_agent"]
        b = r["single_agent_baseline"]
        print(f"{t:<32} | {'Multi-Agent':<14} | {m['f1']:<6.2f} | {m['precision']:<10.2f} | {m['recall']:<8.2f} | {m['duration_sec']:<8.3f}")
        print(f"{'':<32} | {'Single-Agent':<14} | {b['f1']:<6.2f} | {b['precision']:<10.2f} | {b['recall']:<8.2f} | {b['duration_sec']:<8.3f}")
        print("-" * 90)

    return results


if __name__ == "__main__":
    asyncio.run(run_all_benchmarks())
