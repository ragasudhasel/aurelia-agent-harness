"""Unit tests for JSONL trace logging, secret redaction, and offline replay."""

import json
import os
import tempfile
from core.trace import TraceLogger, replay_trace


def test_trace_logging_and_replay():
    """Verify writing events to JSONL trace and offline replay reconstruction."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TraceLogger(run_id="run_trace_test", trace_dir=tmpdir)
        logger.log_event("run_started", details={"task": "test"})
        logger.log_event("task_started", agent_id="bug_agent", task_id="t1")
        logger.log_event("tool_call", agent_id="bug_agent", details={"tool": "list_files"})
        logger.log_event("checker_approved", agent_id="bug_agent", details={"verified": 1})
        logger.log_event("run_completed", details={"status": "succeeded"})

        trace_file = logger.trace_file_path
        assert os.path.exists(trace_file)

        # Read offline replay
        replay_summary = replay_trace(trace_file)
        assert replay_summary["run_id"] == "run_trace_test"
        assert replay_summary["run_status"] == "succeeded"
        assert replay_summary["total_events"] == 5
        assert replay_summary["tool_calls_count"] == 1
        assert replay_summary["checker_events_count"] == 1


def test_trace_secret_redaction():
    """Verify secrets are redacted before being written to disk."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TraceLogger(run_id="run_redact_test", trace_dir=tmpdir)
        logger.log_event(
            "model_call",
            details={
                "api_key": "sk-12345678901234567890abcdef",
                "auth": "Bearer secret_bearer_token_123456789"
            }
        )

        with open(logger.trace_file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "sk-1234567890" not in content
        assert "[REDACTED_API_KEY]" in content
        assert "[REDACTED_BEARER_TOKEN]" in content
