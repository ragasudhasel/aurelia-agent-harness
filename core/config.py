"""Configuration models and YAML loader for the task-agnostic multi-agent harness."""

import os
from typing import Dict, List, Optional, Any
import yaml
from pydantic import BaseModel, Field, ConfigDict, field_validator


class BudgetLimits(BaseModel):
    """Budget limits for global run or per-agent execution."""
    model_config = ConfigDict(extra="forbid")

    max_steps: int = Field(default=20, ge=1, description="Maximum execution steps/tool actions")
    max_wall_time_sec: float = Field(default=60.0, gt=0.0, description="Maximum elapsed seconds")
    max_tokens: int = Field(default=25000, ge=100, description="Maximum estimated token usage")
    max_model_calls: int = Field(default=10, ge=1, description="Maximum model invocations")
    max_rejection_cycles: int = Field(default=2, ge=0, description="Maximum checker rejection iterations")


class RetryConfig(BaseModel):
    """Retry policy for transient failures."""
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=3, ge=1)
    initial_backoff_sec: float = Field(default=0.2, ge=0.0)
    backoff_multiplier: float = Field(default=2.0, ge=1.0)
    jitter: bool = Field(default=True)
    retryable_error_types: List[str] = Field(
        default_factory=lambda: ["RateLimitError", "TemporaryNetworkError", "TimeoutError"]
    )


class CheckerConfig(BaseModel):
    """Configuration for two-layer output checker."""
    model_config = ConfigDict(extra="forbid")

    max_rejection_cycles: int = Field(default=2, ge=0)
    deterministic_enabled: bool = Field(default=True)
    semantic_enabled: bool = Field(default=True)
    fail_closed: bool = Field(default=True, description="Fail closed on errors: reject if verification cannot complete")


class ChaosConfig(BaseModel):
    """Controlled chaos simulation for failure testing."""
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False)
    target_agent: Optional[str] = Field(default=None)
    failure_type: Optional[str] = Field(
        default=None,
        description="One of: 'timeout', 'tool_error', 'transient_network', 'rejection'"
    )


class AgentConfig(BaseModel):
    """Configuration for an individual specialist agent."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Unique agent identifier, e.g. bug_agent")
    role: str = Field(..., description="Specialist role title")
    description: str = Field(...)
    instructions: str = Field(..., description="Specialist system prompt instructions")
    permitted_tools: List[str] = Field(default_factory=list, description="Allowlist of tool names")
    budget: BudgetLimits = Field(default_factory=BudgetLimits)
    output_schema_type: str = Field(default="SpecialistOutput")


class HarnessConfig(BaseModel):
    """Complete root configuration for an orchestration task."""
    model_config = ConfigDict(extra="forbid")

    task_name: str = Field(..., description="Name of the task, e.g. RepoSentinel or IncidentPilot")
    task_type: str = Field(..., description="e.g. code_review, incident_investigation")
    description: str = Field(...)
    workspace_root: str = Field(default=".", description="Root directory path for safe file access")
    lead_agent_instructions: str = Field(...)
    agents: Dict[str, AgentConfig] = Field(..., description="Configured specialist agents")
    global_budget: BudgetLimits = Field(default_factory=BudgetLimits)
    retry_config: RetryConfig = Field(default_factory=RetryConfig)
    checker_config: CheckerConfig = Field(default_factory=CheckerConfig)
    chaos_config: ChaosConfig = Field(default_factory=ChaosConfig)
    model_provider: str = Field(default="mock", description="'mock' for offline testing or 'openai'/'provider'")
    model_name: str = Field(default="mock-agent-v1")
    trace_dir: str = Field(default="./runs")
    require_human_approval_for_risky_tools: bool = Field(default=True)

    @field_validator("agents")
    @classmethod
    def validate_minimum_agents(cls, v: Dict[str, AgentConfig]) -> Dict[str, AgentConfig]:
        if len(v) < 3:
            raise ValueError(f"Harness requires a minimum of 3 distinct specialist agents. Found {len(v)}.")
        return v


def load_config(config_path: str, base_dir: Optional[str] = None) -> HarnessConfig:
    """
    Load and validate a YAML harness configuration file.
    Resolves relative workspace_root paths relative to config directory or base_dir.
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        raw_data = yaml.safe_load(f)

    if not isinstance(raw_data, dict):
        raise ValueError(f"Invalid YAML content in {config_path}: expected mapping.")

    # Resolve workspace_root if relative
    workspace = raw_data.get("workspace_root", ".")
    if not os.path.isabs(workspace):
        if base_dir:
            anchor = base_dir
        elif os.path.exists(os.path.join(os.getcwd(), workspace)):
            anchor = os.getcwd()
        else:
            anchor = os.path.dirname(os.path.abspath(config_path))
        raw_data["workspace_root"] = os.path.normpath(os.path.join(anchor, workspace))

    # Parse through Pydantic
    return HarnessConfig.model_validate(raw_data)
