"""Unit tests for configuration parsing, validation, and minimum agent requirements."""

import os
import pytest
from pydantic import ValidationError
from core.config import load_config, HarnessConfig, BudgetLimits


def test_load_reposentinel_config():
    """Verify loading and validating configs/reposentinel.yaml."""
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "configs", "reposentinel.yaml")
    config = load_config(cfg_path)
    assert config.task_name == "RepoSentinel"
    assert config.task_type == "code_review"
    assert len(config.agents) >= 3
    assert "bug_agent" in config.agents
    assert "security_agent" in config.agents
    assert "test_agent" in config.agents


def test_load_incidentpilot_config():
    """Verify loading and validating configs/incidentpilot.yaml."""
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "configs", "incidentpilot.yaml")
    config = load_config(cfg_path)
    assert config.task_name == "IncidentPilot"
    assert config.task_type == "incident_investigation"
    assert len(config.agents) >= 3
    assert "log_agent" in config.agents
    assert "incident_agent" in config.agents
    assert "mitigation_agent" in config.agents


def test_minimum_three_agents_enforcement(sample_config):
    """Enforce that harness requires at least 3 distinct specialist agents."""
    # Attempt to create config with only 2 agents
    two_agents = {
        "ag1": sample_config.agents["bug_agent"],
        "ag2": sample_config.agents["security_agent"]
    }
    with pytest.raises(ValidationError) as exc:
        HarnessConfig(
            task_name="InvalidHarness",
            task_type="test",
            description="Insufficient agents",
            lead_agent_instructions="Lead instructions",
            agents=two_agents
        )
    assert "minimum of 3 distinct specialist agents" in str(exc.value)


def test_invalid_negative_budget():
    """Verify budget values must be positive."""
    with pytest.raises(ValidationError):
        BudgetLimits(max_steps=-5)

    with pytest.raises(ValidationError):
        BudgetLimits(max_wall_time_sec=0.0)
