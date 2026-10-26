"""Shared pytest fixtures for Task D."""

import os
import sys
import tempfile
import pytest

# Ensure task-d root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.config import HarnessConfig, AgentConfig, BudgetLimits, RetryConfig, CheckerConfig, ChaosConfig
from core.model_client import MockModelClient
from tools.security_guard import ToolRegistry
from tools.repository import list_repository_files, read_repository_file, get_line_numbered_snippet


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory populated with sample files for deterministic testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # File 1: cart.py with intentional calculation defect
        cart_path = os.path.join(tmpdir, "cart.py")
        with open(cart_path, "w", encoding="utf-8") as f:
            f.write(
                "def calculate_total(items):\n"
                "    total = sum(items)\n"
                "    if total > 100:\n"
                "        return total * 0.9\n"
                "    return total\n"
            )

        # File 2: db.py with intentional SQL injection
        db_path = os.path.join(tmpdir, "db.py")
        with open(db_path, "w", encoding="utf-8") as f:
            f.write(
                "def query_user(user_input):\n"
                "    query = f\"SELECT * FROM users WHERE name = '{user_input}'\"\n"
                "    return query\n"
            )

        # File 3: test_cart.py
        test_path = os.path.join(tmpdir, "test_cart.py")
        with open(test_path, "w", encoding="utf-8") as f:
            f.write(
                "from cart import calculate_total\n"
                "def test_cart():\n"
                "    assert calculate_total([10, 20]) == 30\n"
            )

        yield tmpdir


@pytest.fixture
def sample_config(temp_workspace):
    """Provide a validated HarnessConfig pointing to temp_workspace."""
    return HarnessConfig(
        task_name="TestSentinel",
        task_type="code_review",
        description="Testing multi-agent review configuration",
        workspace_root=temp_workspace,
        lead_agent_instructions="Decompose task into bug, security, and test subtasks.",
        global_budget=BudgetLimits(max_steps=30, max_wall_time_sec=30.0, max_tokens=20000, max_model_calls=15),
        retry_config=RetryConfig(max_attempts=3, initial_backoff_sec=0.01),
        checker_config=CheckerConfig(max_rejection_cycles=2, deterministic_enabled=True, semantic_enabled=True),
        chaos_config=ChaosConfig(enabled=False),
        model_provider="mock",
        model_name="mock-test-v1",
        trace_dir=os.path.join(temp_workspace, "runs"),
        require_human_approval_for_risky_tools=True,
        agents={
            "bug_agent": AgentConfig(
                name="bug_agent",
                role="Bug Specialist",
                description="Finds logic bugs",
                instructions="Identify functional bugs with exact line numbers.",
                permitted_tools=["list_repository_files", "read_repository_file", "get_line_numbered_snippet"],
                budget=BudgetLimits(max_steps=10, max_wall_time_sec=15.0)
            ),
            "security_agent": AgentConfig(
                name="security_agent",
                role="Security Specialist",
                description="Finds security vulnerabilities",
                instructions="Identify vulnerabilities with exact line numbers.",
                permitted_tools=["list_repository_files", "read_repository_file", "get_line_numbered_snippet"],
                budget=BudgetLimits(max_steps=10, max_wall_time_sec=15.0)
            ),
            "test_agent": AgentConfig(
                name="test_agent",
                role="Test Specialist",
                description="Finds missing test cases",
                instructions="Identify untested cases with line numbers.",
                permitted_tools=["list_repository_files", "read_repository_file"],
                budget=BudgetLimits(max_steps=10, max_wall_time_sec=15.0)
            )
        }
    )


@pytest.fixture
def mock_model_client():
    return MockModelClient(model_name="mock-test-v1")


@pytest.fixture
def tool_registry():
    registry = ToolRegistry(human_approval_callback=lambda a, t, k: False)
    registry.register_tool("list_repository_files", list_repository_files, "List files", is_risky=False)
    registry.register_tool("read_repository_file", read_repository_file, "Read file", is_risky=False)
    registry.register_tool("get_line_numbered_snippet", get_line_numbered_snippet, "Get snippet", is_risky=False)
    return registry
