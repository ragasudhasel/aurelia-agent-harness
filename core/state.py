"""Central, inspectable, asyncio-safe RunState manager."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from core.schemas import (
    TaskDefinition,
    TaskStatus,
    RunStatus,
    AgentMessage,
    Finding,
    SpecialistOutput,
    CheckerDecision,
    FinalReport,
    ExecutionMetrics
)


class RunState:
    """
    Central, thread/asyncio-safe run-state object.
    Tracks run lifecycle, structured messages, intermediate results, verified findings,
    checker decisions, errors, and resource usage.
    """

    def __init__(self, run_id: str, task_name: str, user_task: str):
        self.run_id = run_id
        self.task_name = task_name
        self.user_task = user_task
        self.status = RunStatus.PENDING
        self.start_time: Optional[datetime] = None
        self.finish_time: Optional[datetime] = None

        # Task definitions and status tracking
        self.tasks: Dict[str, TaskDefinition] = {}
        self.task_statuses: Dict[str, TaskStatus] = {}
        self.agent_statuses: Dict[str, str] = {}
        self.execution_attempts: Dict[str, int] = {}

        # Message bus / handoffs
        self.messages: List[AgentMessage] = []

        # Intermediate & verified outputs
        self.intermediate_results: Dict[str, SpecialistOutput] = {}
        self.verified_findings: List[Finding] = []
        self.rejected_outputs: List[Dict[str, Any]] = []
        self.checker_decisions: Dict[str, List[CheckerDecision]] = {}

        # Failures and errors
        self.errors: List[Dict[str, Any]] = []
        self.partial_failures: List[Dict[str, Any]] = []
        self.retry_events: List[Dict[str, Any]] = []

        # Resource counters
        self.step_counts: Dict[str, int] = {}
        self.token_counts: Dict[str, int] = {}
        self.model_calls_count: int = 0
        self.tool_calls_count: int = 0

        # Final synthesized report
        self.final_report: Optional[FinalReport] = None

        # Async lock for safe concurrent mutations
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            self.status = RunStatus.RUNNING
            self.start_time = datetime.now(timezone.utc)

    async def finish(self, final_status: RunStatus) -> None:
        async with self._lock:
            self.status = final_status
            self.finish_time = datetime.now(timezone.utc)

    async def add_task(self, task: TaskDefinition) -> None:
        async with self._lock:
            self.tasks[task.task_id] = task
            self.task_statuses[task.task_id] = TaskStatus.PENDING
            self.execution_attempts[task.task_id] = 0

    async def set_task_status(self, task_id: str, status: TaskStatus) -> None:
        async with self._lock:
            self.task_statuses[task_id] = status

    async def set_agent_status(self, agent_id: str, status_desc: str) -> None:
        async with self._lock:
            self.agent_statuses[agent_id] = status_desc

    async def record_message(self, message: AgentMessage) -> None:
        async with self._lock:
            self.messages.append(message)

    async def record_intermediate_result(self, task_id: str, output: SpecialistOutput) -> None:
        async with self._lock:
            self.intermediate_results[task_id] = output
            self.tool_calls_count += output.tool_calls_count

    async def record_checker_decision(self, task_id: str, decision: CheckerDecision) -> None:
        async with self._lock:
            if task_id not in self.checker_decisions:
                self.checker_decisions[task_id] = []
            self.checker_decisions[task_id].append(decision)

    async def add_verified_findings(self, findings: List[Finding]) -> None:
        async with self._lock:
            # Deduplicate by title & file_path
            existing_keys = {
                (f.category, f.title, f.file_path, f.line_number) for f in self.verified_findings
            }
            for f in findings:
                key = (f.category, f.title, f.file_path, f.line_number)
                if key not in existing_keys:
                    self.verified_findings.append(f)
                    existing_keys.add(key)

    async def add_rejected_output(self, task_id: str, output: SpecialistOutput, reasons: List[str]) -> None:
        async with self._lock:
            self.rejected_outputs.append({
                "task_id": task_id,
                "agent_id": output.agent_id,
                "summary": output.summary,
                "findings_count": len(output.findings),
                "reasons": reasons,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

    async def record_retry(self, agent_id: str, attempt: int, error_msg: str, delay: float) -> None:
        async with self._lock:
            self.retry_events.append({
                "agent_id": agent_id,
                "attempt": attempt,
                "error": error_msg,
                "delay_sec": delay,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

    async def record_error(self, agent_id: str, error_msg: str, fatal: bool = False, task_id: Optional[str] = None) -> None:
        async with self._lock:
            err_data = {
                "agent_id": agent_id,
                "task_id": task_id,
                "error": error_msg,
                "fatal": fatal,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            self.errors.append(err_data)
            if fatal and task_id:
                self.partial_failures.append(err_data)

    async def record_step(self, agent_id: str) -> None:
        async with self._lock:
            self.step_counts[agent_id] = self.step_counts.get(agent_id, 0) + 1

    async def record_tokens(self, agent_id: str, tokens: int) -> None:
        async with self._lock:
            self.token_counts[agent_id] = self.token_counts.get(agent_id, 0) + tokens
            self.model_calls_count += 1

    def get_metrics(self, budget_manager: Optional[Any] = None) -> ExecutionMetrics:
        """Calculate aggregated metrics at the current moment."""
        duration = 0.0
        if self.start_time:
            end = self.finish_time or datetime.now(timezone.utc)
            duration = max(0.0, (end - self.start_time).total_seconds())

        if budget_manager:
            total_steps = budget_manager.global_steps
            total_tokens = budget_manager.global_tokens
            total_model_calls = budget_manager.global_model_calls
        else:
            total_steps = sum(self.step_counts.values())
            total_tokens = sum(self.token_counts.values())
            total_model_calls = self.model_calls_count

        total_rejections = sum(len(decisions) - 1 for decisions in self.checker_decisions.values() if decisions)

        agent_breakdown = {}
        all_agents = set(list(self.step_counts.keys()) + list(self.token_counts.keys()))
        if budget_manager:
            all_agents.update(budget_manager.agent_steps.keys())
            all_agents.update(budget_manager.agent_tokens.keys())

        for ag in all_agents:
            steps = budget_manager.agent_steps.get(ag, 0) if budget_manager else self.step_counts.get(ag, 0)
            tokens = budget_manager.agent_tokens.get(ag, 0) if budget_manager else self.token_counts.get(ag, 0)
            agent_breakdown[ag] = {
                "steps": steps,
                "tokens": tokens,
            }

        return ExecutionMetrics(
            total_duration_sec=round(duration, 3),
            step_count=total_steps,
            token_count=total_tokens,
            model_calls=total_model_calls,
            tool_calls=self.tool_calls_count,
            retries_count=len(self.retry_events),
            rejection_cycles_count=max(0, total_rejections),
            agent_breakdown=agent_breakdown
        )
