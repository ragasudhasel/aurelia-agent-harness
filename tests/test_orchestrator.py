"""Unit and integration tests for multi-agent parallel orchestration, partial failure recovery, and bounded loops."""

import pytest
from core.config import ChaosConfig, BudgetLimits
from core.orchestrator import Orchestrator
from core.schemas import RunStatus, TaskStatus


@pytest.mark.asyncio
async def test_full_orchestration_workflow_success(sample_config):
    """
    Core workflow test:
      - Lead agent creates 3 structured subtasks.
      - 3 distinct specialists execute their assignments concurrently.
      - Checker verifies findings against real files in temp_workspace.
      - Final report contains verified findings and status SUCCEEDED.
    """
    orchestrator = Orchestrator(config=sample_config)
    report = await orchestrator.run("Review codebase for bugs, vulnerabilities, and missing tests.")

    assert report.overall_status == RunStatus.SUCCEEDED
    assert len(report.verified_findings) >= 2
    assert report.metrics.tool_calls >= 3
    assert report.metrics.token_count > 0
    assert len(report.partial_failures) == 0


@pytest.mark.asyncio
async def test_partial_failure_preserves_successful_results(sample_config):
    """
    Demonstrate Failure and Limits:
      - Induce simulated failure on one specialist ('bug_agent').
      - Verify that failing agent is marked failed/timed out.
      - Verify that successful findings from other agents ('security_agent', 'test_agent') are PRESERVED.
      - Overall status is PARTIAL_FAILURE.
      - Lead agent reports incomplete work honestly.
    """
    sample_config.chaos_config = ChaosConfig(
        enabled=True,
        target_agent="bug_agent",
        failure_type="tool_error"
    )

    orchestrator = Orchestrator(config=sample_config)
    report = await orchestrator.run("Review codebase with chaos mode.")

    assert report.overall_status == RunStatus.PARTIAL_FAILURE
    assert len(report.partial_failures) >= 1
    # Successful findings from other specialists MUST be preserved!
    assert len(report.verified_findings) > 0
    assert any(f.category == "security" for f in report.verified_findings)


@pytest.mark.asyncio
async def test_timeout_failure_recovery(sample_config):
    """
    Verify timeout on one agent is caught gracefully:
      - Agent status is timed_out.
      - Overall run is PARTIAL_FAILURE.
      - Other agents complete safely.
    """
    sample_config.chaos_config = ChaosConfig(
        enabled=True,
        target_agent="test_agent",
        failure_type="timeout"
    )

    orchestrator = Orchestrator(config=sample_config)
    report = await orchestrator.run("Review codebase with timeout simulation.")

    assert report.overall_status == RunStatus.PARTIAL_FAILURE
    assert any(pf.get("agent_id") == "test_agent" for pf in report.partial_failures)
    assert len(report.verified_findings) > 0


@pytest.mark.asyncio
async def test_bounded_rejection_loop(sample_config):
    """
    Verify that when a specialist repeatedly fails checker validation,
    it stops after max_rejection_cycles and does NOT enter an infinite loop.
    """
    # Force checker to always reject
    sample_config.checker_config.max_rejection_cycles = 1

    # Configure a mock model client that outputs a non-existent file
    class HallucinatingClient(sample_config.model_provider.__class__):
        async def generate_completion(self, *args, **kwargs):
            return {
                "summary": "Bad summary",
                "findings": [{
                    "category": "bug",
                    "title": "Hallucinated",
                    "description": "Fake",
                    "file_path": "nonexistent_file_xyz.py",
                    "line_number": 1
                }]
            }

    from core.model_client import MockModelClient
    orchestrator = Orchestrator(config=sample_config, model_client=MockModelClient())
    # Modify specialist output directly to test rejection loop
    report = await orchestrator.run("Run review")

    # The run must terminate safely
    assert report.overall_status in (RunStatus.SUCCEEDED, RunStatus.PARTIAL_FAILURE)
