"""Unit tests for Pydantic v2 schemas and validation rules."""

import pytest
from pydantic import ValidationError
from core.schemas import (
    TaskDefinition,
    AgentMessage,
    Finding,
    SpecialistOutput,
    CheckerDecision,
    MessageType,
    Severity,
    FailedCheckDetail
)


def test_task_definition_validation():
    """Verify TaskDefinition strictly enforces required fields and denies extra fields."""
    task = TaskDefinition(
        task_id="task_1",
        assigned_agent="bug_agent",
        objective="Find off-by-one errors",
        context={"focus": "math"},
        dependencies=[]
    )
    assert task.task_id == "task_1"
    assert task.assigned_agent == "bug_agent"

    with pytest.raises(ValidationError):
        # Missing required objective
        TaskDefinition(task_id="task_2", assigned_agent="bug_agent")


def test_finding_line_number_validation():
    """Verify Finding validator enforces line_end >= line_number."""
    # Valid finding
    f = Finding(
        category="bug",
        severity=Severity.HIGH,
        title="Logic error",
        description="Incorrect calculation",
        line_number=10,
        line_end=15
    )
    assert f.line_end == 15

    # Invalid finding: line_end < line_number
    with pytest.raises(ValidationError) as exc:
        Finding(
            category="bug",
            title="Bad lines",
            description="End before start",
            line_number=20,
            line_end=10
        )
    assert "line_end (10) cannot be less than line_number (20)" in str(exc.value)


def test_agent_message_creation():
    """Verify AgentMessage structure and timestamp generation."""
    msg = AgentMessage(
        sender="lead_agent",
        recipient="bug_agent",
        run_id="run_100",
        message_type=MessageType.TASK_ASSIGNMENT,
        payload={"param": 42}
    )
    assert msg.message_id is not None
    assert msg.sender == "lead_agent"
    assert msg.payload["param"] == 42


def test_checker_decision_validation():
    """Verify CheckerDecision model validation."""
    decision = CheckerDecision(
        approved=False,
        rejection_cycle=1,
        failed_checks=[
            FailedCheckDetail(
                rule="invalid_path",
                message="File does not exist",
                offending_value="missing.py"
            )
        ]
    )
    assert not decision.approved
    assert decision.rejection_cycle == 1
    assert len(decision.failed_checks) == 1
