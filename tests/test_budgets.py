"""Unit tests for BudgetManager enforcing step, token, time, and cycle limits."""

import time
import pytest
from core.config import BudgetLimits
from core.budgets import BudgetManager, BudgetExhaustedError, TimeoutExceededError


def test_global_step_limit():
    """Verify global step limit stops execution when exhausted."""
    mgr = BudgetManager(global_budget=BudgetLimits(max_steps=3))
    mgr.consume_step("agent_a")
    mgr.consume_step("agent_b")
    mgr.consume_step("agent_a")

    with pytest.raises(BudgetExhaustedError) as exc:
        mgr.consume_step("agent_b")
    assert "Global run exhausted max_steps limit" in str(exc.value)


def test_per_agent_step_limit():
    """Verify individual agent step limit is enforced independently."""
    global_b = BudgetLimits(max_steps=20)
    agent_b = {
        "agent_a": BudgetLimits(max_steps=2),
        "agent_b": BudgetLimits(max_steps=5),
    }
    mgr = BudgetManager(global_budget=global_b, agent_budgets=agent_b)

    mgr.consume_step("agent_a")
    mgr.consume_step("agent_a")

    # agent_a exceeds its limit (2)
    with pytest.raises(BudgetExhaustedError) as exc:
        mgr.consume_step("agent_a")
    assert "Agent 'agent_a' exhausted max_steps limit" in str(exc.value)

    # agent_b can still execute within its limit
    mgr.consume_step("agent_b")
    assert mgr.agent_steps["agent_b"] == 1


def test_token_limit_enforcement():
    """Verify token accumulation raises error when exceeding budget ceiling."""
    mgr = BudgetManager(global_budget=BudgetLimits(max_tokens=1000))
    mgr.record_tokens("agent_a", 600)

    with pytest.raises(BudgetExhaustedError) as exc:
        mgr.record_tokens("agent_a", 500)
    assert "exhausted max_tokens limit" in str(exc.value)


def test_wall_clock_timeout_enforcement():
    """Verify wall-clock time limit triggers TimeoutExceededError."""
    # Set a very low timeout of 0.05 seconds
    mgr = BudgetManager(global_budget=BudgetLimits(max_wall_time_sec=0.05))
    mgr.start_agent_timer("agent_a")
    time.sleep(0.06)

    with pytest.raises(TimeoutExceededError) as exc:
        mgr.consume_step("agent_a")
    assert "exhausted wall_clock_time limit" in str(exc.value)


def test_rejection_cycle_limit():
    """Verify rejection cycle limit enforcement."""
    mgr = BudgetManager(global_budget=BudgetLimits())
    assert mgr.record_rejection_cycle("task_1", max_cycles=2) == 1
    assert mgr.record_rejection_cycle("task_1", max_cycles=2) == 2

    with pytest.raises(BudgetExhaustedError) as exc:
        mgr.record_rejection_cycle("task_1", max_cycles=2)
    assert "max_rejection_cycles" in str(exc.value)
