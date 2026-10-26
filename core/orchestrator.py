"""Asynchronous multi-agent orchestrator with dependency resolution, parallel execution, and failure recovery."""

import asyncio
import logging
import uuid
from typing import Dict, List, Optional, Set
from core.config import HarnessConfig
from core.schemas import (
    TaskDefinition,
    TaskStatus,
    RunStatus,
    MessageType,
    AgentMessage,
    SpecialistOutput,
    FinalReport,
)
from core.state import RunState
from core.budgets import BudgetManager, BudgetExhaustedError, TimeoutExceededError
from core.retry import execute_with_retry
from core.trace import TraceLogger
from core.model_client import BaseModelClient, MockModelClient, ProviderModelClient
from tools.security_guard import ToolRegistry
from tools.repository import (
    list_repository_files,
    read_repository_file,
    get_line_numbered_snippet,
    run_permitted_test_command,
)
from tools.log_parser import parse_log_file, group_errors, reconstruct_timeline
from agents.lead import LeadAgent
from agents.specialist import SpecialistAgent
from agents.checker import OutputChecker

logger = logging.getLogger("orchestrator")


class Orchestrator:
    """
    Coordinates multi-agent execution:
      - Enforces execution budgets and timeouts.
      - Resolves topological task dependencies and executes independent tasks concurrently.
      - Dispatches subtasks, handles two-layer validation loops, and recovers from partial failures.
      - Produces append-only JSONL traces and synthesizes final reports.
    """

    def __init__(
        self,
        config: HarnessConfig,
        model_client: Optional[BaseModelClient] = None,
        tool_registry: Optional[ToolRegistry] = None,
    ):
        self.config = config

        # 1. Initialize model client
        if model_client:
            self.model_client = model_client
        elif config.model_provider == "mock":
            self.model_client = MockModelClient(model_name=config.model_name)
        else:
            api_key = config.model_name  # Or env var
            self.model_client = ProviderModelClient(api_key=api_key, model_name=config.model_name)

        # 2. Initialize tool registry with safe defaults
        self.tool_registry = tool_registry or self._build_default_tool_registry()

        # 3. Output Checker
        self.checker = OutputChecker(
            workspace_root=self.config.workspace_root,
            config=self.config.checker_config,
            model_client=self.model_client
        )

    def _build_default_tool_registry(self) -> ToolRegistry:
        """Register safe and risky tools."""
        registry = ToolRegistry(
            human_approval_callback=lambda agent, tool, kwargs: not self.config.require_human_approval_for_risky_tools
        )
        registry.register_tool(
            "list_repository_files",
            list_repository_files,
            "List permitted repository files in workspace",
            is_risky=False
        )
        registry.register_tool(
            "read_repository_file",
            read_repository_file,
            "Read file contents within workspace",
            is_risky=False
        )
        registry.register_tool(
            "get_line_numbered_snippet",
            get_line_numbered_snippet,
            "Retrieve line-numbered code snippet",
            is_risky=False
        )
        registry.register_tool(
            "parse_log_file",
            parse_log_file,
            "Parse application incident log file",
            is_risky=False
        )
        registry.register_tool(
            "group_errors",
            group_errors,
            "Group parsed log errors by signature",
            is_risky=False
        )
        registry.register_tool(
            "reconstruct_timeline",
            reconstruct_timeline,
            "Reconstruct chronological error event timeline",
            is_risky=False
        )
        registry.register_tool(
            "run_permitted_test_command",
            run_permitted_test_command,
            "Run static analysis or unit test command (RISKY)",
            is_risky=True
        )
        return registry

    async def run(self, user_task: str, run_id: Optional[str] = None) -> FinalReport:
        """
        Execute full multi-agent orchestration lifecycle.
        """
        run_id = run_id or f"run_{uuid.uuid4().hex[:10]}"
        state = RunState(run_id=run_id, task_name=self.config.task_name, user_task=user_task)
        trace = TraceLogger(run_id=run_id, trace_dir=self.config.trace_dir)

        # Build BudgetManager
        agent_budgets = {name: meta.budget for name, meta in self.config.agents.items()}
        budget = BudgetManager(global_budget=self.config.global_budget, agent_budgets=agent_budgets)
        self.tool_registry.trace_logger = trace

        lead = LeadAgent(config=self.config, model_client=self.model_client, budget_manager=budget)

        # Instantiate specialist agents
        specialists: Dict[str, SpecialistAgent] = {}
        for name, agent_meta in self.config.agents.items():
            specialists[name] = SpecialistAgent(
                config=agent_meta,
                tool_registry=self.tool_registry,
                model_client=self.model_client,
                workspace_root=self.config.workspace_root,
                budget_manager=budget
            )

        # -------------------------------------------------------------
        # Phase 1: Run Initialization & Decomposition
        # -------------------------------------------------------------
        await state.start()
        trace.log_event("run_started", details={"task_name": self.config.task_name, "user_task": user_task})

        try:
            subtasks = await lead.plan_and_decompose(user_task)
            for t in subtasks:
                await state.add_task(t)
            trace.log_event("task_decomposed", details={"subtasks_count": len(subtasks)})
        except Exception as exc:
            logger.error(f"LeadAgent decomposition failed: {exc}")
            await state.record_error("lead_agent", str(exc), fatal=True)
            await state.finish(RunStatus.FAILED)
            trace.log_event("run_failed", details={"error": str(exc)})
            return await lead.synthesize_final_report(
                run_id=run_id,
                user_task=user_task,
                overall_status=RunStatus.FAILED,
                verified_findings=[],
                unverified_or_rejected=[],
                partial_failures=state.partial_failures,
                metrics=state.get_metrics()
            )

        # -------------------------------------------------------------
        # Phase 2: Parallel Dependency-Aware Execution
        # -------------------------------------------------------------
        pending_tasks = set(state.tasks.keys())
        completed_tasks: Set[str] = set()

        while pending_tasks:
            budget.check_time_limit()

            # Find tasks whose dependencies are fully completed
            ready_tasks = [
                tid for tid in pending_tasks
                if all(dep in completed_tasks for dep in state.tasks[tid].dependencies)
            ]

            if not ready_tasks:
                # Deadlock / unresolvable dependency
                logger.error(f"Dependency deadlock detected among pending tasks: {pending_tasks}")
                for tid in pending_tasks:
                    await state.set_task_status(tid, TaskStatus.SKIPPED)
                break

            # Execute ready tasks in parallel
            coros = [
                self._execute_specialist_subtask(
                    task_id=tid,
                    task_def=state.tasks[tid],
                    specialists=specialists,
                    state=state,
                    trace=trace,
                    budget=budget
                )
                for tid in ready_tasks
            ]

            # Use asyncio.gather with return_exceptions=True to preserve successes
            results = await asyncio.gather(*coros, return_exceptions=True)

            for tid, result in zip(ready_tasks, results):
                pending_tasks.remove(tid)
                completed_tasks.add(tid)
                if isinstance(result, Exception):
                    logger.error(f"Task '{tid}' raised unhandled exception: {result}")
                    agent_name = state.tasks[tid].assigned_agent
                    trace.log_event("agent_failed", agent_id=agent_name, task_id=tid, details={"error": str(result)})
                    await state.set_task_status(tid, TaskStatus.FAILED)
                    await state.record_error(agent_name, str(result), fatal=True, task_id=tid)

        # -------------------------------------------------------------
        # Phase 3: Run Evaluation & Final Synthesis
        # -------------------------------------------------------------
        # Determine overall status
        any_success = any(st == TaskStatus.SUCCEEDED for st in state.task_statuses.values())
        any_failure = any(
            st in (TaskStatus.FAILED, TaskStatus.TIMED_OUT, TaskStatus.REJECTED, TaskStatus.SKIPPED)
            for st in state.task_statuses.values()
        )

        if any_success and not any_failure:
            overall_status = RunStatus.SUCCEEDED
        elif any_success and any_failure:
            overall_status = RunStatus.PARTIAL_FAILURE
        else:
            overall_status = RunStatus.FAILED

        await state.finish(overall_status)
        metrics = state.get_metrics(budget_manager=budget)

        final_report = await lead.synthesize_final_report(
            run_id=run_id,
            user_task=user_task,
            overall_status=overall_status,
            verified_findings=state.verified_findings,
            unverified_or_rejected=state.rejected_outputs,
            partial_failures=state.partial_failures,
            metrics=metrics
        )
        state.final_report = final_report

        trace.log_event("run_completed", details={
            "status": overall_status.value,
            "metrics": metrics.model_dump(),
            "findings_count": len(state.verified_findings)
        })

        return final_report

    async def _execute_specialist_subtask(
        self,
        task_id: str,
        task_def: TaskDefinition,
        specialists: Dict[str, SpecialistAgent],
        state: RunState,
        trace: TraceLogger,
        budget: BudgetManager
    ) -> Optional[SpecialistOutput]:
        """
        Execute an individual specialist task with retries, timeouts, and bounded checker rejection loops.
        """
        agent_name = task_def.assigned_agent
        specialist = specialists.get(agent_name)

        if not specialist:
            await state.set_task_status(task_id, TaskStatus.FAILED)
            await state.record_error(agent_name, f"Assigned agent '{agent_name}' not configured.", fatal=True, task_id=task_id)
            return None

        # Check chaos mode simulation
        if self.config.chaos_config.enabled and self.config.chaos_config.target_agent == agent_name:
            failure_type = self.config.chaos_config.failure_type
            if failure_type == "timeout":
                logger.warning(f"CHAOS MODE: Inducing simulated timeout for agent '{agent_name}'")
                await asyncio.sleep(0.1)
                raise TimeoutExceededError(agent_name, 65.0, 60.0)
            elif failure_type == "tool_error":
                logger.warning(f"CHAOS MODE: Inducing simulated tool failure for agent '{agent_name}'")
                raise RuntimeError(f"Simulated chaos tool error on agent '{agent_name}'.")

        budget.start_agent_timer(agent_name)
        await state.set_task_status(task_id, TaskStatus.RUNNING)
        await state.set_agent_status(agent_name, "running")

        trace.log_event("task_started", agent_id=agent_name, task_id=task_id, details={"objective": task_def.objective})

        # Structured message: assignment handoff
        assign_msg = AgentMessage(
            sender="lead_agent",
            recipient=agent_name,
            run_id=state.run_id,
            task_id=task_id,
            message_type=MessageType.TASK_ASSIGNMENT,
            payload={"objective": task_def.objective, "context": task_def.context}
        )
        await state.record_message(assign_msg)

        rejection_cycle = 0
        previous_feedback = None

        while True:
            budget.check_time_limit(agent_name)

            # 1. Execute task with retry support
            async def run_specialist():
                return await specialist.execute_task(task_def, previous_rejection=previous_feedback)

            try:
                output: SpecialistOutput = await execute_with_retry(
                    coro_func=run_specialist,
                    agent_id=agent_name,
                    retry_config=self.config.retry_config,
                    budget_manager=budget,
                    on_retry_callback=lambda ag, att, err, delay: state.record_retry(ag, att, err, delay)
                )
            except TimeoutExceededError as timeout_err:
                logger.error(f"Task '{task_id}' timed out: {timeout_err}")
                await state.set_task_status(task_id, TaskStatus.TIMED_OUT)
                await state.record_error(agent_name, str(timeout_err), fatal=True, task_id=task_id)
                trace.log_event("task_timed_out", agent_id=agent_name, task_id=task_id, details={"error": str(timeout_err)})
                return None
            except BudgetExhaustedError as b_err:
                logger.error(f"Task '{task_id}' budget exhausted: {b_err}")
                await state.set_task_status(task_id, TaskStatus.FAILED)
                await state.record_error(agent_name, str(b_err), fatal=True, task_id=task_id)
                trace.log_event("budget_exhausted", agent_id=agent_name, task_id=task_id, details={"error": str(b_err)})
                return None
            except Exception as exc:
                logger.error(f"Task '{task_id}' failed: {exc}")
                await state.set_task_status(task_id, TaskStatus.FAILED)
                await state.record_error(agent_name, str(exc), fatal=True, task_id=task_id)
                trace.log_event("task_failed", agent_id=agent_name, task_id=task_id, details={"error": str(exc)})
                return None

            await state.record_intermediate_result(task_id, output)

            # Record handoff message
            result_msg = AgentMessage(
                sender=agent_name,
                recipient="output_checker",
                run_id=state.run_id,
                task_id=task_id,
                message_type=MessageType.TASK_RESULT,
                payload={"summary": output.summary, "findings_count": len(output.findings)}
            )
            await state.record_message(result_msg)

            # 2. Output Checker validation
            decision = await self.checker.check_output(output, current_cycle=rejection_cycle)
            await state.record_checker_decision(task_id, decision)

            if decision.approved:
                await state.add_verified_findings(output.findings)
                await state.set_task_status(task_id, TaskStatus.SUCCEEDED)
                await state.set_agent_status(agent_name, "succeeded")
                trace.log_event(
                    "checker_approved",
                    agent_id=agent_name,
                    task_id=task_id,
                    details={"cycle": rejection_cycle, "verified_findings": len(output.findings)}
                )
                return output
            else:
                # Validation failure
                rejection_cycle += 1
                trace.log_event(
                    "checker_rejected",
                    agent_id=agent_name,
                    task_id=task_id,
                    details={
                        "cycle": rejection_cycle,
                        "reasons": [f.message for f in decision.failed_checks]
                    }
                )

                # Check rejection budget limit
                max_cycles = self.config.checker_config.max_rejection_cycles
                if rejection_cycle > max_cycles:
                    logger.warning(f"Task '{task_id}' exceeded max rejection cycles ({max_cycles}). Marking REJECTED.")
                    await state.set_task_status(task_id, TaskStatus.REJECTED)
                    await state.add_rejected_output(
                        task_id=task_id,
                        output=output,
                        reasons=[f.message for f in decision.failed_checks]
                    )
                    await state.record_error(
                        agent_name,
                        f"Output rejected by checker after {max_cycles} cycles.",
                        fatal=True,
                        task_id=task_id
                    )
                    return None

                # Provide feedback message for revision
                feedback_msg = AgentMessage(
                    sender="output_checker",
                    recipient=agent_name,
                    run_id=state.run_id,
                    task_id=task_id,
                    message_type=MessageType.CHECKER_FEEDBACK,
                    payload={"cycle": rejection_cycle, "failed_checks": [f.model_dump() for f in decision.failed_checks]}
                )
                await state.record_message(feedback_msg)
                previous_feedback = decision.failed_checks
