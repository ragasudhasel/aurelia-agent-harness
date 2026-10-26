"""BaselineAgent: monolithic single-agent baseline for comparative benchmarking."""

import logging
import time
from typing import Dict, Any, List
from core.schemas import FinalReport, Finding, RunStatus, ExecutionMetrics, Severity
from core.model_client import BaseModelClient
from tools.security_guard import ToolRegistry

logger = logging.getLogger("baseline_agent")


class BaselineAgent:
    """
    Monolithic single-agent baseline.
    Attempts to perform the entire task (bug inspection, security review, and testing)
    sequentially within a single agent prompt, without specialist decomposition or parallelization.
    """

    def __init__(
        self,
        workspace_root: str,
        tool_registry: ToolRegistry,
        model_client: BaseModelClient
    ):
        self.name = "single_agent_baseline"
        self.workspace_root = workspace_root
        self.tool_registry = tool_registry
        self.model_client = model_client

    async def run(self, user_task: str, run_id: str) -> FinalReport:
        """Run single-agent baseline execution."""
        start_time = time.monotonic()
        tool_calls = 0

        # Step 1: List files
        file_list: List[str] = []
        if self.tool_registry.is_tool_registered("list_repository_files"):
            file_list = await self.tool_registry.execute_tool(
                agent_id=self.name,
                permitted_tools=["list_repository_files", "read_repository_file"],
                tool_name="list_repository_files",
                workspace_root=self.workspace_root
            )
            tool_calls += 1

        # Step 2: Read candidate file
        sample_file = file_list[0] if file_list else None
        sample_line = 1
        sample_snippet = ""
        if sample_file and self.tool_registry.is_tool_registered("read_repository_file"):
            content = await self.tool_registry.execute_tool(
                agent_id=self.name,
                permitted_tools=["list_repository_files", "read_repository_file"],
                tool_name="read_repository_file",
                workspace_root=self.workspace_root,
                file_path=sample_file
            )
            tool_calls += 1
            lines = content.splitlines()
            if lines:
                sample_snippet = lines[0]

        # Step 3: Single monolithic completion
        prompt = (
            f"You are a generalist software assistant. Perform complete analysis for: {user_task}\n"
            f"Files: {file_list}\n"
            f"Identify all bugs, security risks, and test gaps in a single response."
        )

        resp = await self.model_client.generate_completion(
            prompt=prompt,
            system_instruction="You are a single generalist software reviewer.",
            context={
                "agent_name": self.name,
                "sample_file": sample_file,
                "sample_line": sample_line,
                "sample_snippet": sample_snippet
            }
        )

        raw_findings = resp.get("findings", [])
        verified_findings = [Finding(**f) for f in raw_findings]
        elapsed = time.monotonic() - start_time

        metrics = ExecutionMetrics(
            total_duration_sec=round(elapsed, 3),
            step_count=tool_calls + 1,
            token_count=350,
            model_calls=1,
            tool_calls=tool_calls,
            retries_count=0,
            rejection_cycles_count=0,
            agent_breakdown={self.name: {"steps": tool_calls + 1, "tokens": 350}}
        )

        return FinalReport(
            run_id=run_id,
            task_name="Baseline Single-Agent Review",
            user_task=user_task,
            overall_status=RunStatus.SUCCEEDED,
            verified_findings=verified_findings,
            unverified_or_rejected=[],
            partial_failures=[],
            summary=resp.get("summary", "Baseline analysis complete."),
            metrics=metrics
        )
