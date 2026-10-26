"""Structured Pydantic v2 schemas for agents, messages, findings, handoffs, and final reports."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field, ConfigDict, field_validator


class TaskStatus(str, Enum):
    """Explicit lifecycle status transitions for tasks."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class RunStatus(str, Enum):
    """Overall status of an orchestration run."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MessageType(str, Enum):
    """Structured message handoff categories."""
    TASK_ASSIGNMENT = "task_assignment"
    TASK_PROGRESS = "task_progress"
    TASK_RESULT = "task_result"
    CHECKER_FEEDBACK = "checker_feedback"
    REVISION_SUBMITTED = "revision_submitted"
    FINAL_RESPONSE = "final_response"


class Severity(str, Enum):
    """Defect/incident severity levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class TaskDefinition(BaseModel):
    """Structured subtask created by the Lead Agent."""
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(..., description="Unique subtask identifier, e.g. task_bug_analysis")
    assigned_agent: str = Field(..., description="Name of the specialist agent, e.g. bug_agent")
    objective: str = Field(..., description="Clear objective of the subtask")
    context: Dict[str, Any] = Field(default_factory=dict, description="Context, files, parameters needed")
    dependencies: List[str] = Field(default_factory=list, description="List of task_ids that must complete first")
    expected_output_schema: str = Field(default="SpecialistOutput", description="Name of the expected output schema")


class AgentMessage(BaseModel):
    """Structured message for all communication and handoffs between agents."""
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender: str = Field(..., description="Agent or component sending the message")
    recipient: str = Field(..., description="Agent or component receiving the message")
    run_id: str = Field(..., description="Execution run identifier")
    task_id: Optional[str] = Field(default=None, description="Associated task ID if applicable")
    message_type: MessageType = Field(..., description="Type of structured handoff")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Message contents")
    evidence: Optional[str] = Field(default=None, description="Supporting evidence snippet or file reference")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Finding(BaseModel):
    """Structured, verified finding (bug, security flaw, test gap, or root cause)."""
    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(default_factory=lambda: f"FND-{uuid.uuid4().hex[:8].upper()}")
    category: str = Field(..., description="Category, e.g. bug, security, test, incident")
    severity: Severity = Field(default=Severity.MEDIUM)
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field(...)
    file_path: Optional[str] = Field(default=None, description="Relative path within workspace root")
    line_number: Optional[int] = Field(default=None, ge=1, description="Starting 1-indexed line number")
    line_end: Optional[int] = Field(default=None, ge=1, description="Ending line number")
    evidence_snippet: Optional[str] = Field(default=None, description="Exact code or log snippet supporting finding")
    suggested_fix: Optional[str] = Field(default=None, description="Recommended remediation")

    @field_validator("line_end")
    @classmethod
    def check_line_range(cls, v: Optional[int], info) -> Optional[int]:
        line_start = info.data.get("line_number")
        if v is not None and line_start is not None and v < line_start:
            raise ValueError(f"line_end ({v}) cannot be less than line_number ({line_start})")
        return v


class SpecialistOutput(BaseModel):
    """Validated structured output produced by a specialist agent."""
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(..., description="Identity of the reporting specialist")
    task_id: str = Field(..., description="Subtask identifier")
    summary: str = Field(..., description="Executive summary of findings")
    findings: List[Finding] = Field(default_factory=list, description="List of structured findings")
    raw_notes: Optional[str] = Field(default=None, description="Supporting analysis or logs")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Execution metadata")
    tool_calls_count: int = Field(default=0, ge=0)


class FailedCheckDetail(BaseModel):
    """Specific rule violation detected by the Output Checker."""
    model_config = ConfigDict(extra="forbid")

    rule: str = Field(..., description="Name of rule violated, e.g. path_traversal_attempt, invalid_line_number")
    message: str = Field(..., description="Detailed description of why check failed")
    offending_value: Optional[str] = Field(default=None, description="The invalid string or number")
    suggested_action: Optional[str] = Field(default=None, description="How specialist should correct the output")


class CheckerDecision(BaseModel):
    """Decision record produced by the Output Checker."""
    model_config = ConfigDict(extra="forbid")

    approved: bool = Field(..., description="True if output passed deterministic and semantic review")
    rejection_cycle: int = Field(default=0, ge=0, description="Current rejection cycle (0 = first review)")
    failed_checks: List[FailedCheckDetail] = Field(default_factory=list, description="List of rule failures")
    semantic_notes: Optional[str] = Field(default=None, description="Feedback from semantic review")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExecutionMetrics(BaseModel):
    """Comprehensive resource and operational metrics for an execution run."""
    model_config = ConfigDict(extra="forbid")

    total_duration_sec: float = Field(default=0.0, ge=0.0)
    step_count: int = Field(default=0, ge=0)
    token_count: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    retries_count: int = Field(default=0, ge=0)
    rejection_cycles_count: int = Field(default=0, ge=0)
    agent_breakdown: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class FinalReport(BaseModel):
    """Final synthesized response produced by Lead Agent and Orchestrator."""
    model_config = ConfigDict(extra="forbid")

    run_id: str
    task_name: str
    user_task: str
    overall_status: RunStatus
    verified_findings: List[Finding] = Field(default_factory=list)
    unverified_or_rejected: List[Dict[str, Any]] = Field(default_factory=list)
    partial_failures: List[Dict[str, Any]] = Field(default_factory=list)
    summary: str
    metrics: ExecutionMetrics
