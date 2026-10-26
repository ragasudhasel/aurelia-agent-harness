"""Unit tests for exponential backoff, jitter, and transient vs permanent error handling."""

import pytest
from core.config import RetryConfig
from core.retry import execute_with_retry, is_transient_error


class TransientNetworkError(Exception):
    pass


def test_is_transient_error_classification():
    """Verify distinction between retryable transient and permanent errors."""
    transient_types = ["RateLimitError", "TemporaryNetworkError", "TimeoutError"]

    # Permanent errors
    assert not is_transient_error(FileNotFoundError("No such file"), transient_types)
    assert not is_transient_error(ValueError("Bad parameter"), transient_types)
    assert not is_transient_error(KeyError("missing"), transient_types)

    # Transient errors
    assert is_transient_error(RuntimeError("Rate limit exceeded 429"), transient_types)
    assert is_transient_error(RuntimeError("Connection refused by peer"), transient_types)


@pytest.mark.asyncio
async def test_retry_on_transient_error():
    """Verify function retries on transient error and succeeds once transient error clears."""
    attempts = 0

    async def flaky_call():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("Temporary 429 Rate limit reached")
        return "SUCCESS"

    cfg = RetryConfig(max_attempts=4, initial_backoff_sec=0.01)
    retries_recorded = []

    res = await execute_with_retry(
        coro_func=flaky_call,
        agent_id="test_agent",
        retry_config=cfg,
        on_retry_callback=lambda ag, att, err, d: retries_recorded.append((att, err))
    )

    assert res == "SUCCESS"
    assert attempts == 3
    assert len(retries_recorded) == 2


@pytest.mark.asyncio
async def test_no_retry_on_permanent_error():
    """Verify permanent errors abort immediately without burning retry attempts."""
    attempts = 0

    async def broken_call():
        nonlocal attempts
        attempts += 1
        raise FileNotFoundError("Missing file")

    cfg = RetryConfig(max_attempts=3, initial_backoff_sec=0.01)

    with pytest.raises(FileNotFoundError):
        await execute_with_retry(
            coro_func=broken_call,
            agent_id="test_agent",
            retry_config=cfg
        )

    # Must only have been attempted once!
    assert attempts == 1
