"""Retry engine with exponential backoff, jitter, and transient error classification."""

import asyncio
import logging
import random
from typing import Callable, TypeVar, Any, Optional
from core.config import RetryConfig
from core.budgets import BudgetManager, BudgetExhaustedError

logger = logging.getLogger("retry")

T = TypeVar("T")

# Non-retryable permanent error types
PERMANENT_ERROR_NAMES = {
    "ValidationError",
    "SecurityViolationError",
    "BudgetExhaustedError",
    "TimeoutExceededError",
    "FileNotFoundError",
    "ValueError",
    "KeyError",
}


def is_transient_error(exc: Exception, configured_transient_types: list[str]) -> bool:
    """Determine whether an exception is transient (safe to retry) or permanent."""
    exc_name = type(exc).__name__
    if exc_name in PERMANENT_ERROR_NAMES:
        return False

    # Check if explicitly listed as transient
    if exc_name in configured_transient_types:
        return True

    # Check common transient strings
    err_str = str(exc).lower()
    transient_indicators = ["rate limit", "timeout", "connection refused", "network", "429", "503"]
    return any(ind in err_str for ind in transient_indicators)


async def execute_with_retry(
    coro_func: Callable[[], Any],
    agent_id: str,
    retry_config: RetryConfig,
    budget_manager: Optional[BudgetManager] = None,
    on_retry_callback: Optional[Callable[[str, int, str, float], Any]] = None,
) -> Any:
    """
    Execute an asynchronous callable with exponential backoff, jitter, and budget checking.
    """
    attempt = 0
    delay = retry_config.initial_backoff_sec

    while True:
        attempt += 1
        try:
            if budget_manager:
                budget_manager.consume_step(agent_id)
            return await coro_func()
        except Exception as exc:
            # If not transient or attempts exhausted, raise immediately
            is_transient = is_transient_error(exc, retry_config.retryable_error_types)

            if not is_transient or attempt >= retry_config.max_attempts:
                logger.warning(
                    f"Agent '{agent_id}' aborting on attempt {attempt}/{retry_config.max_attempts}: "
                    f"{type(exc).__name__}: {exc} (transient={is_transient})"
                )
                raise exc

            # Calculate backoff with jitter
            jitter_factor = random.uniform(0.8, 1.2) if retry_config.jitter else 1.0
            actual_delay = delay * jitter_factor

            logger.info(
                f"Agent '{agent_id}' encountered transient error ({type(exc).__name__}). "
                f"Retrying in {actual_delay:.2f}s (attempt {attempt}/{retry_config.max_attempts})..."
            )

            if on_retry_callback:
                res = on_retry_callback(agent_id, attempt, str(exc), actual_delay)
                if asyncio.iscoroutine(res):
                    await res

            await asyncio.sleep(actual_delay)
            delay *= retry_config.backoff_multiplier
