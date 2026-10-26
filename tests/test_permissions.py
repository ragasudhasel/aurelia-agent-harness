"""Unit tests for tool permissions, human approval gates, and path traversal defenses."""

import os
import pytest
from tools.safe_file_access import resolve_safe_path, SecurityViolationError
from tools.security_guard import ToolRegistry, PermissionDeniedError, HumanApprovalDeniedError


def test_path_traversal_prevention(temp_workspace):
    """Verify that path traversal attempts ('../') are blocked and raise SecurityViolationError."""
    # Attempting to navigate outside workspace root
    with pytest.raises(SecurityViolationError) as exc:
        resolve_safe_path(temp_workspace, "../../../etc/passwd")
    assert "Path traversal detected" in str(exc.value)

    with pytest.raises(SecurityViolationError):
        resolve_safe_path(temp_workspace, "cart/../../outside.txt")


def test_tool_permission_allowlist(tool_registry):
    """Verify agent cannot execute tools outside its permitted_tools list."""
    permitted = ["list_repository_files"]

    # Attempting to execute unauthorized tool
    with pytest.raises(PermissionDeniedError) as exc:
        import asyncio
        asyncio.run(tool_registry.execute_tool(
            agent_id="test_agent",
            permitted_tools=permitted,
            tool_name="read_repository_file",
            file_path="cart.py"
        ))
    assert "does not have permission to execute tool 'read_repository_file'" in str(exc.value)


@pytest.mark.asyncio
async def test_human_approval_for_risky_tool():
    """Verify risky tools trigger human approval callback and raise error if denied."""
    approved_actions = False

    def human_gate(agent_id, tool_name, kwargs):
        return approved_actions

    reg = ToolRegistry(human_approval_callback=human_gate)
    reg.register_tool(
        "run_risky_command",
        lambda cmd: f"Executed {cmd}",
        description="Risky action",
        is_risky=True
    )

    # 1. Denied approval
    with pytest.raises(HumanApprovalDeniedError) as exc:
        await reg.execute_tool(
            agent_id="agent_1",
            permitted_tools=["run_risky_command"],
            tool_name="run_risky_command",
            cmd="rm -rf /"
        )
    assert "denied by human supervisor" in str(exc.value)

    # 2. Granted approval
    approved_actions = True
    result = await reg.execute_tool(
        agent_id="agent_1",
        permitted_tools=["run_risky_command"],
        tool_name="run_risky_command",
        cmd="pytest"
    )
    assert "Executed pytest" in result
