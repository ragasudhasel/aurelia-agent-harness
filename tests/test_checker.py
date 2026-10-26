"""Unit tests for the two-layer Output Checker and bounded rejection loop."""

import pytest
from core.config import CheckerConfig
from core.schemas import SpecialistOutput, Finding, Severity
from agents.checker import OutputChecker
from core.model_client import MockModelClient


@pytest.fixture
def checker(temp_workspace, mock_model_client):
    cfg = CheckerConfig(max_rejection_cycles=2, deterministic_enabled=True, semantic_enabled=True)
    return OutputChecker(workspace_root=temp_workspace, config=cfg, model_client=mock_model_client)


@pytest.mark.asyncio
async def test_checker_approves_valid_finding(checker):
    """Verify checker approves finding with physically existing file, line, and snippet."""
    valid_output = SpecialistOutput(
        agent_id="bug_agent",
        task_id="t1",
        summary="Found calculation bug",
        findings=[
            Finding(
                category="bug",
                severity=Severity.HIGH,
                title="Off-by-one threshold",
                description="Threshold error in cart.py",
                file_path="cart.py",
                line_number=2,
                line_end=4,
                evidence_snippet="total = sum(items)\nif total > 100:",
                suggested_fix="Change to >= 100"
            )
        ]
    )

    decision = await checker.check_output(valid_output)
    assert decision.approved
    assert len(decision.failed_checks) == 0


@pytest.mark.asyncio
async def test_checker_rejects_nonexistent_file(checker):
    """Verify checker rejects finding pointing to non-existent file."""
    bad_output = SpecialistOutput(
        agent_id="bug_agent",
        task_id="t1",
        summary="Hallucinated finding",
        findings=[
            Finding(
                category="bug",
                title="Imaginary bug",
                description="File does not exist",
                file_path="imaginary_file_not_found.py",
                line_number=5,
                evidence_snippet="def fake(): pass"
            )
        ]
    )

    decision = await checker.check_output(bad_output)
    assert not decision.approved
    assert any(f.rule == "nonexistent_file_path" for f in decision.failed_checks)


@pytest.mark.asyncio
async def test_checker_rejects_invalid_line_number(checker):
    """Verify checker rejects line number exceeding total file line count."""
    bad_output = SpecialistOutput(
        agent_id="bug_agent",
        task_id="t1",
        summary="Line out of bounds",
        findings=[
            Finding(
                category="bug",
                title="Bad line number",
                description="Exceeds 5 total lines",
                file_path="cart.py",
                line_number=999,  # cart.py only has ~5 lines
                evidence_snippet="def calculate_total(items):"
            )
        ]
    )

    decision = await checker.check_output(bad_output)
    assert not decision.approved
    assert any(f.rule == "invalid_line_number" for f in decision.failed_checks)


@pytest.mark.asyncio
async def test_checker_rejects_mismatched_snippet(checker):
    """Verify checker rejects fabricated snippet that does not match physical file content."""
    bad_output = SpecialistOutput(
        agent_id="bug_agent",
        task_id="t1",
        summary="Mismatched code snippet",
        findings=[
            Finding(
                category="bug",
                title="Fabricated evidence",
                description="Snippet not in cart.py",
                file_path="cart.py",
                line_number=1,
                evidence_snippet="this_variable_does_not_exist = 123456789"
            )
        ]
    )

    decision = await checker.check_output(bad_output)
    assert not decision.approved
    assert any(f.rule == "mismatched_evidence_snippet" for f in decision.failed_checks)


@pytest.mark.asyncio
async def test_checker_fails_closed_on_error(temp_workspace):
    """Verify checker fails closed (rejects) if semantic validation raises an unhandled error."""
    class FailingModelClient(MockModelClient):
        async def generate_completion(self, *args, **kwargs):
            raise RuntimeError("Model service down 500")

    failing_checker = OutputChecker(
        workspace_root=temp_workspace,
        config=CheckerConfig(semantic_enabled=True, fail_closed=True),
        model_client=FailingModelClient()
    )

    output = SpecialistOutput(
        agent_id="test_agent",
        task_id="t1",
        summary="Test summary",
        findings=[Finding(category="test", title="Test finding", description="Valid file", file_path="cart.py", line_number=1)]
    )

    decision = await failing_checker.check_output(output)
    # Must fail closed: not approved!
    assert not decision.approved
    assert any(f.rule == "semantic_checker_failure" for f in decision.failed_checks)
