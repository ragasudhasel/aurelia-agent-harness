"""BudgetManager: enforcing global and per-agent execution, step, token, and time limits."""

import time
from typing import Dict, Optional, Any
from core.config import BudgetLimits


class BudgetExhaustedError(Exception):
    """Raised when an execution budget limit is reached."""
    def __init__(self, limit_type: str, agent_id: Optional[str], current_value: Any, max_value: Any):
        self.limit_type = limit_type
        self.agent_id = agent_id
        self.current_value = current_value
        self.max_value = max_value
        scope = f"Agent '{agent_id}'" if agent_id else "Global run"
        super().__init__(
            f"{scope} exhausted {limit_type} limit: reached {current_value} (max {max_value})."
        )


class TimeoutExceededError(BudgetExhaustedError):
    """Raised when wall-clock execution time limit is reached."""
    def __init__(self, agent_id: Optional[str], elapsed_sec: float, max_sec: float):
        super().__init__("wall_clock_time", agent_id, round(elapsed_sec, 2), max_sec)


class BudgetManager:
    """
    Dedicated manager that tracks and enforces execution constraints during runtime.
    Protects against runaway execution loops and resource exhaustion.
    """

    def __init__(
        self,
        global_budget: BudgetLimits,
        agent_budgets: Optional[Dict[str, BudgetLimits]] = None
    ):
        self.global_budget = global_budget
        self.agent_budgets = agent_budgets or {}

        # Global counters
        self.global_steps = 0
        self.global_tokens = 0
        self.global_model_calls = 0
        self.start_monotonic = time.monotonic()

        # Per-agent counters
        self.agent_steps: Dict[str, int] = {}
        self.agent_tokens: Dict[str, int] = {}
        self.agent_model_calls: Dict[str, int] = {}
        self.agent_start_time: Dict[str, float] = {}
        self.agent_rejection_cycles: Dict[str, int] = {}

    def start_agent_timer(self, agent_id: str) -> None:
        """Start the wall-clock timer for an individual agent."""
        self.agent_start_time[agent_id] = time.monotonic()

    def check_time_limit(self, agent_id: Optional[str] = None) -> None:
        """Enforce global and per-agent wall-clock execution timeouts."""
        now = time.monotonic()

        # 1. Global time check
        elapsed_global = now - self.start_monotonic
        if elapsed_global > self.global_budget.max_wall_time_sec:
            raise TimeoutExceededError(None, elapsed_global, self.global_budget.max_wall_time_sec)

        # 2. Per-agent time check
        if agent_id and agent_id in self.agent_start_time:
            elapsed_agent = now - self.agent_start_time[agent_id]
            agent_limit = self.agent_budgets.get(agent_id, self.global_budget).max_wall_time_sec
            if elapsed_agent > agent_limit:
                raise TimeoutExceededError(agent_id, elapsed_agent, agent_limit)

    def consume_step(self, agent_id: str) -> None:
        """
        Record and check execution step limit before taking action.
        Throws BudgetExhaustedError if limit exceeded.
        """
        self.check_time_limit(agent_id)

        # Increment global
        self.global_steps += 1
        if self.global_steps > self.global_budget.max_steps:
            raise BudgetExhaustedError("max_steps", None, self.global_steps, self.global_budget.max_steps)

        # Increment agent
        current_agent_steps = self.agent_steps.get(agent_id, 0) + 1
        self.agent_steps[agent_id] = current_agent_steps

        agent_limit = self.agent_budgets.get(agent_id, self.global_budget).max_steps
        if current_agent_steps > agent_limit:
            raise BudgetExhaustedError("max_steps", agent_id, current_agent_steps, agent_limit)

    def consume_model_call(self, agent_id: str) -> None:
        """Record a model invocation and enforce model-call limit."""
        self.check_time_limit(agent_id)

        self.global_model_calls += 1
        if self.global_model_calls > self.global_budget.max_model_calls:
            raise BudgetExhaustedError("max_model_calls", None, self.global_model_calls, self.global_budget.max_model_calls)

        current = self.agent_model_calls.get(agent_id, 0) + 1
        self.agent_model_calls[agent_id] = current

        agent_limit = self.agent_budgets.get(agent_id, self.global_budget).max_model_calls
        if current > agent_limit:
            raise BudgetExhaustedError("max_model_calls", agent_id, current, agent_limit)

    def record_tokens(self, agent_id: str, tokens: int) -> None:
        """Record token consumption and enforce token ceiling."""
        self.global_tokens += tokens
        if self.global_tokens > self.global_budget.max_tokens:
            raise BudgetExhaustedError("max_tokens", None, self.global_tokens, self.global_budget.max_tokens)

        current = self.agent_tokens.get(agent_id, 0) + tokens
        self.agent_tokens[agent_id] = current

        agent_limit = self.agent_budgets.get(agent_id, self.global_budget).max_tokens
        if current > agent_limit:
            raise BudgetExhaustedError("max_tokens", agent_id, current, agent_limit)

    def record_rejection_cycle(self, task_id: str, max_cycles: int) -> int:
        """Record a checker rejection cycle and raise error if cycle limit reached."""
        current = self.agent_rejection_cycles.get(task_id, 0) + 1
        self.agent_rejection_cycles[task_id] = current
        if current > max_cycles:
            raise BudgetExhaustedError("max_rejection_cycles", task_id, current, max_cycles)
        return current
