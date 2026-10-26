"""Append-only JSONL execution tracing with automatic secret redaction and offline replay."""

import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from tools.security_guard import redact_sensitive_data


class TraceLogger:
    """
    Append-only JSONL logger recording all multi-agent events, tool invocations,
    checker decisions, and budget events with automatic secret redaction.
    """

    def __init__(self, run_id: str, trace_dir: str = "./runs"):
        self.run_id = run_id
        safe_folder_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in run_id)
        self.run_folder = os.path.join(trace_dir, safe_folder_name)
        os.makedirs(self.run_folder, exist_ok=True)
        self.trace_file_path = os.path.join(self.run_folder, "trace.jsonl")

    def log_event(
        self,
        event_type: str,
        agent_id: Optional[str] = None,
        task_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append an event record to trace.jsonl after applying secret redaction."""
        record = {
            "run_id": self.run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "agent_id": agent_id,
            "task_id": task_id,
            "details": details or {},
        }

        # Apply deterministic redaction
        serialized = json.dumps(record, default=str)
        safe_serialized = redact_sensitive_data(serialized)

        with open(self.trace_file_path, "a", encoding="utf-8") as f:
            f.write(safe_serialized + "\n")


def replay_trace(trace_file_path: str) -> Dict[str, Any]:
    """
    Offline trace replayer: parses trace.jsonl and reconstructs the execution timeline,
    agent states, tool calls, and final outputs without invoking any LLMs or tool side-effects.
    """
    if not os.path.exists(trace_file_path):
        raise FileNotFoundError(f"Trace file not found: {trace_file_path}")

    events: List[Dict[str, Any]] = []
    agent_timeline: Dict[str, List[Dict[str, Any]]] = {}
    tool_calls: List[Dict[str, Any]] = []
    checker_events: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    run_status = "UNKNOWN"
    run_id = None
    start_time = None
    end_time = None

    with open(trace_file_path, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if not line_str:
                continue
            event = json.loads(line_str)
            events.append(event)

            ev_type = event.get("event_type")
            ts = event.get("timestamp")
            ag = event.get("agent_id")

            if not run_id:
                run_id = event.get("run_id")
            if not start_time:
                start_time = ts
            end_time = ts

            if ag:
                if ag not in agent_timeline:
                    agent_timeline[ag] = []
                agent_timeline[ag].append({"timestamp": ts, "event": ev_type, "details": event.get("details")})

            if ev_type == "tool_call":
                tool_calls.append(event)
            elif "checker" in ev_type:
                checker_events.append(event)
            elif ev_type in ("agent_failed", "timeout_exceeded", "budget_exhausted", "partial_failure"):
                failures.append(event)
            elif ev_type == "run_completed":
                run_status = event.get("details", {}).get("status", "COMPLETED")

    return {
        "run_id": run_id,
        "run_status": run_status,
        "start_time": start_time,
        "end_time": end_time,
        "total_events": len(events),
        "events": events,
        "agent_timeline": agent_timeline,
        "tool_calls_count": len(tool_calls),
        "checker_events_count": len(checker_events),
        "failures_count": len(failures),
        "failures": failures,
    }
