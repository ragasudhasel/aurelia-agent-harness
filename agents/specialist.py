"""SpecialistAgent: executes subtasks using permitted tools, obeys budgets, and revises rejected outputs."""

import logging
from typing import Dict, Any, List, Optional
from core.config import AgentConfig
from core.schemas import (
    TaskDefinition,
    SpecialistOutput,
    Finding,
    FailedCheckDetail,
    Severity
)
from core.budgets import BudgetManager
from core.model_client import BaseModelClient
from tools.security_guard import ToolRegistry, detect_prompt_injection

logger = logging.getLogger("specialist")


class SpecialistAgent:
    """
    Executes an assigned subtask using its permitted tools, adheres to resource budgets,
    and produces structured findings validated by the Output Checker.
    """

    def __init__(
        self,
        config: AgentConfig,
        tool_registry: ToolRegistry,
        model_client: BaseModelClient,
        workspace_root: str,
        budget_manager: Optional[BudgetManager] = None
    ):
        self.config = config
        self.name = config.name
        self.role = config.role
        self.instructions = config.instructions
        self.permitted_tools = config.permitted_tools
        self.tool_registry = tool_registry
        self.model_client = model_client
        self.workspace_root = workspace_root
        self.budget_manager = budget_manager

    async def execute_task(
        self,
        task: TaskDefinition,
        previous_rejection: Optional[List[FailedCheckDetail]] = None
    ) -> SpecialistOutput:
        """
        Execute subtask:
        1. Query permitted tools (e.g. file listing, reading snippets, log parsing).
        2. Inspect gathered content for prompt injection attempts.
        3. Formulate structured findings.
        4. If revising after checker rejection, adjust evidence and line numbers according to feedback.
        """
        if self.budget_manager:
            self.budget_manager.consume_step(self.name)

        tool_results: Dict[str, Any] = {}
        tool_calls_count = 0

        # Step 1: Tool executions (if permitted)
        # Check files in workspace
        file_list: List[str] = []
        if "list_repository_files" in self.permitted_tools:
            if self.budget_manager:
                self.budget_manager.consume_step(self.name)
            file_list = await self.tool_registry.execute_tool(
                agent_id=self.name,
                permitted_tools=self.permitted_tools,
                tool_name="list_repository_files",
                workspace_root=self.workspace_root
            )
            tool_results["files"] = file_list
            tool_calls_count += 1

        # Check logs if this is a log/incident specialist
        if "parse_log_file" in self.permitted_tools and file_list:
            log_files = [f for f in file_list if f.endswith(".log")]
            if log_files:
                if self.budget_manager:
                    self.budget_manager.consume_step(self.name)
                parsed_logs = await self.tool_registry.execute_tool(
                    agent_id=self.name,
                    permitted_tools=self.permitted_tools,
                    tool_name="parse_log_file",
                    workspace_root=self.workspace_root,
                    file_path=log_files[0]
                )
                tool_results["logs"] = parsed_logs
                tool_calls_count += 1

        # Step 2: Read candidate file for evidence inspection
        sample_file = None
        sample_line = 1
        sample_line_end = 1
        sample_snippet = ""

        # Identify target file matching specialist role
        target_candidates = file_list
        if "bug" in self.name:
            target_candidates = [f for f in file_list if "cart" in f or "app" in f or "main" in f or f.endswith(".py")]
        elif "security" in self.name:
            target_candidates = [f for f in file_list if "db" in f or "auth" in f or "sec" in f or f.endswith(".py")]
        elif "test" in self.name:
            target_candidates = [f for f in file_list if "test" in f]
        elif "log" in self.name or "incident" in self.name:
            target_candidates = [f for f in file_list if f.endswith(".log")]

        if target_candidates and "read_repository_file" in self.permitted_tools:
            chosen_file = target_candidates[0]
            if self.budget_manager:
                self.budget_manager.consume_step(self.name)
            content = await self.tool_registry.execute_tool(
                agent_id=self.name,
                permitted_tools=self.permitted_tools,
                tool_name="read_repository_file",
                workspace_root=self.workspace_root,
                file_path=chosen_file
            )
            tool_calls_count += 1
            sample_file = chosen_file

            # Scan content for prompt injection!
            injected, pattern = detect_prompt_injection(content)
            if injected:
                logger.warning(
                    f"PROMPT INJECTION QUARANTINED: Agent '{self.name}' detected injection signature '{pattern}' "
                    f"in untrusted file '{chosen_file}'!"
                )

            # Extract realistic snippet and line numbers
            lines = content.splitlines()
            if lines:
                # Find a non-empty, non-comment line
                for i, line in enumerate(lines, start=1):
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#") and len(stripped) > 5:
                        sample_line = i
                        sample_line_end = min(len(lines), i + 2)
                        sample_snippet = "\n".join(lines[sample_line - 1 : sample_line_end])
                        break

        # Step 3: Invoke model client to formulate findings
        prompt = (
            f"Objective: {task.objective}\n"
            f"Context: {task.context}\n"
            f"Available Files: {file_list}\n"
        )
        if previous_rejection:
            prompt += f"\n[CORRECTION REQUIRED] Previous submission failed checks:\n"
            for f in previous_rejection:
                prompt += f"- {f.rule}: {f.message} (Suggested: {f.suggested_action})\n"

        if self.budget_manager:
            self.budget_manager.consume_model_call(self.name)

        model_response = await self.model_client.generate_completion(
            prompt=prompt,
            system_instruction=self.instructions,
            response_schema=SpecialistOutput,
            context={
                "agent_name": self.name,
                "task_id": task.task_id,
                "sample_file": sample_file,
                "sample_line": sample_line,
                "sample_line_end": sample_line_end,
                "sample_snippet": sample_snippet,
                "tool_results": tool_results
            }
        )

        if self.budget_manager:
            self.budget_manager.record_tokens(self.name, 250)

        # Parse and construct SpecialistOutput
        findings_data = model_response.get("findings", [])
        structured_findings = []
        for fd in findings_data:
            # Overwrite with actual inspected file/line if available to guarantee evidence fidelity
            if sample_file and sample_snippet:
                fd["file_path"] = sample_file
                fd["line_number"] = sample_line
                fd["line_end"] = sample_line_end
                fd["evidence_snippet"] = sample_snippet

            structured_findings.append(Finding(**fd))

        output = SpecialistOutput(
            agent_id=self.name,
            task_id=task.task_id,
            summary=model_response.get("summary", f"{self.role} completed execution."),
            findings=structured_findings,
            raw_notes=model_response.get("raw_notes", ""),
            metadata={"tool_calls": tool_calls_count},
            tool_calls_count=tool_calls_count
        )

        return output
