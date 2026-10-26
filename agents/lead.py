"""LeadAgent: decomposes user objectives into structured subtasks, coordinates specialists, and synthesizes final report."""

import logging
from typing import List, Dict, Any, Optional
from core.config import HarnessConfig
from core.schemas import TaskDefinition, FinalReport, RunStatus, Finding, ExecutionMetrics
from core.budgets import BudgetManager
from core.model_client import BaseModelClient

logger = logging.getLogger("lead_agent")


class LeadAgent:
    """
    Coordinates multi-agent workflows:
      1. Decomposes user tasks into typed subtasks with dependencies and assignments.
      2. Synthesizes final verified results into an audit report.
    """

    def __init__(
        self,
        config: HarnessConfig,
        model_client: BaseModelClient,
        budget_manager: Optional[BudgetManager] = None
    ):
        self.name = "lead_agent"
        self.config = config
        self.model_client = model_client
        self.budget_manager = budget_manager

    async def plan_and_decompose(self, user_task: str) -> List[TaskDefinition]:
        """
        Break down user task into structured subtasks mapped to configured specialists.
        """
        if self.budget_manager:
            self.budget_manager.consume_step(self.name)
            self.budget_manager.consume_model_call(self.name)

        available_agents_desc = "\n".join(
            f"- {name} ({meta.role}): {meta.description} (Permitted tools: {meta.permitted_tools})"
            for name, meta in self.config.agents.items()
        )

        prompt = (
            f"User Task: {user_task}\n\n"
            f"Available Specialists:\n{available_agents_desc}\n\n"
            f"Decompose the task into subtasks. Return JSON with 'subtasks': list of objects with "
            f"{{'task_id': str, 'assigned_agent': str, 'objective': str, 'context': dict, 'dependencies': list[str]}}."
        )

        resp = await self.model_client.generate_completion(
            prompt=prompt,
            system_instruction=self.config.lead_agent_instructions,
            context={
                "agent_name": self.name,
                "task_type": self.config.task_type
            }
        )

        if self.budget_manager:
            self.budget_manager.record_tokens(self.name, 250)

        raw_subtasks = resp.get("subtasks", [])
        task_definitions: List[TaskDefinition] = []

        for st in raw_subtasks:
            # Validate assigned agent exists in configuration
            assigned = st.get("assigned_agent")
            if assigned not in self.config.agents:
                # Fallback to first available agent if model hallucinated unknown agent name
                assigned = list(self.config.agents.keys())[0]

            task_definitions.append(TaskDefinition(
                task_id=st["task_id"],
                assigned_agent=assigned,
                objective=st["objective"],
                context=st.get("context", {}),
                dependencies=st.get("dependencies", []),
                expected_output_schema="SpecialistOutput"
            ))

        logger.info(f"LeadAgent decomposed task into {len(task_definitions)} subtasks.")
        return task_definitions

    async def synthesize_final_report(
        self,
        run_id: str,
        user_task: str,
        overall_status: RunStatus,
        verified_findings: List[Finding],
        unverified_or_rejected: List[Dict[str, Any]],
        partial_failures: List[Dict[str, Any]],
        metrics: ExecutionMetrics
    ) -> FinalReport:
        """
        Consolidate verified specialist findings into the final report.
        Honest accounting of verified findings, rejected items, and partial failures.
        """
        if self.budget_manager:
            try:
                self.budget_manager.consume_step(self.name)
                self.budget_manager.consume_model_call(self.name)
            except Exception:
                pass

        prompt = (
            f"Synthesize the execution summary for Task '{self.config.task_name}'.\n"
            f"Status: {overall_status.value}\n"
            f"Verified Findings Count: {len(verified_findings)}\n"
            f"Partial Failures Count: {len(partial_failures)}\n"
            f"Verified Findings Details: {[f.model_dump() for f in verified_findings]}\n"
        )

        resp = await self.model_client.generate_completion(
            prompt=prompt,
            system_instruction="You are a principal engineer synthesizing an executive audit report.",
            context={"agent_name": self.name}
        )

        if self.budget_manager:
            self.budget_manager.record_tokens(self.name, 200)

        summary = resp.get("summary", f"Completed {self.config.task_name} review with status {overall_status.value}.")

        return FinalReport(
            run_id=run_id,
            task_name=self.config.task_name,
            user_task=user_task,
            overall_status=overall_status,
            verified_findings=verified_findings,
            unverified_or_rejected=unverified_or_rejected,
            partial_failures=partial_failures,
            summary=summary,
            metrics=metrics
        )
