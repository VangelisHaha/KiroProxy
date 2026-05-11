"""Request retry and circuit breaker mechanism.

Provides:
- Retryable error detection (by status code and exception type)
- Async retry with exponential backoff
- Circuit breaker pattern with probabilistic recovery
"""
import asyncio
import random
import time
from typing import Callable, Any, Optional, Set

from ..logger import get_logger
from ..env_config import (
    MAX_RETRIES,
    BASE_RETRY_DELAY,
    CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
    CIRCUIT_BREAKER_MAX_BACKOFF,
    CIRCUIT_BREAKER_RETRY_CHANCE,
)

logger = get_logger("retry")

# Retryable status codes
RETRYABLE_STATUS_CODES: Set[int] = {
    408,  # Request Timeout
    429,  # Too Many Requests (rate limited)
    500,  # Internal Server Error
    502,  # Bad Gateway
    503,  # Service Unavailable
    504,  # Gateway Timeout
}

# Non-retryable status codes (return error immediately)
NON_RETRYABLE_STATUS_CODES: Set[int] = {
    400,  # Bad Request
    401,  # Unauthorized
    404,  # Not Found
    422,  # Unprocessable Entity
}


def is_retryable_error(status_code: Optional[int], error: Optional[Exception] = None) -> bool:
    """Determine if an error is retryable."""
    if error:
        error_name = type(error).__name__.lower()
        if any(kw in error_name for kw in ['timeout', 'connect', 'network', 'reset']):
            return True

    if status_code and status_code in RETRYABLE_STATUS_CODES:
        return True

    # 403 can be retryable (token expired, auto-refresh)
    if status_code == 403:
        return True

    return False


def is_non_retryable_error(status_code: Optional[int]) -> bool:
    """Determine if an error is non-retryable."""
    return status_code in NON_RETRYABLE_STATUS_CODES if status_code else False


async def retry_async(
    func: Callable,
    max_retries: int = MAX_RETRIES,
    base_delay: float = BASE_RETRY_DELAY,
    max_delay: float = 10.0,
    on_retry: Optional[Callable[[int, Exception], None]] = None
) -> Any:
    """Async retry with exponential backoff.

    Args:
        func: Async function to execute.
        max_retries: Maximum number of retry attempts.
        base_delay: Base delay in seconds.
        max_delay: Maximum delay in seconds.
        on_retry: Optional callback on each retry.
    """
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            return await func()
        except Exception as e:
            last_error = e

            status_code = getattr(e, 'status_code', None)
            if is_non_retryable_error(status_code):
                raise

            if attempt < max_retries and is_retryable_error(status_code, e):
                delay = min(base_delay * (2 ** attempt), max_delay)

                if on_retry:
                    on_retry(attempt + 1, e)
                else:
                    logger.warning(
                        f"Retry {attempt + 1}/{max_retries}, "
                        f"delay {delay:.1f}s, error: {type(e).__name__}: {e}"
                    )

                await asyncio.sleep(delay)
            else:
                raise

    raise last_error


class RetryableRequest:
    """Retryable request context."""

    def __init__(self, max_retries: int = MAX_RETRIES, base_delay: float = BASE_RETRY_DELAY):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.attempt = 0
        self.last_error = None

    def should_retry(self, status_code: Optional[int] = None, error: Optional[Exception] = None) -> bool:
        """Determine whether to retry."""
        self.attempt += 1
        self.last_error = error

        if self.attempt > self.max_retries:
            return False

        if is_non_retryable_error(status_code):
            return False

        return is_retryable_error(status_code, error)

    async def wait(self):
        """Wait with exponential backoff."""
        delay = min(self.base_delay * (2 ** (self.attempt - 1)), 10.0)
        logger.info(f"Retry {self.attempt}/{self.max_retries}, delay {delay:.1f}s")
        await asyncio.sleep(delay)


class CircuitBreaker:
    """Circuit breaker with exponential backoff and probabilistic retry.

    Tracks failure state for an account/resource and prevents repeated
    calls to a failing backend. Includes probabilistic retry to prevent
    permanent "stuck" state.

    Inspired by kiro-gateway's account_manager.py circuit breaker pattern.
    """

    def __init__(
        self,
        name: str,
        recovery_timeout: int = CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
        max_backoff_multiplier: float = CIRCUIT_BREAKER_MAX_BACKOFF,
        retry_chance: float = CIRCUIT_BREAKER_RETRY_CHANCE,
    ):
        self.name = name
        self.recovery_timeout = recovery_timeout
        self.max_backoff_multiplier = max_backoff_multiplier
        self.retry_chance = retry_chance
        self.consecutive_failures = 0
        self.last_failure_time: float = 0
        self.total_failures = 0
        self.total_successes = 0

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (blocking requests)."""
        if self.consecutive_failures == 0:
            return False

        cooldown = self._get_cooldown()
        elapsed = time.time() - self.last_failure_time

        if elapsed >= cooldown:
            return False

        # Probabilistic retry
        if random.random() < self.retry_chance:
            logger.debug(f"Circuit '{self.name}': probabilistic retry triggered")
            return False

        return True

    def _get_cooldown(self) -> float:
        """Calculate cooldown duration with exponential backoff."""
        if self.consecutive_failures <= 0:
            return 0
        multiplier = min(
            2 ** (self.consecutive_failures - 1),
            self.max_backoff_multiplier,
        )
        return self.recovery_timeout * multiplier

    def record_success(self) -> None:
        """Record a successful request."""
        self.consecutive_failures = 0
        self.total_successes += 1

    def record_failure(self) -> None:
        """Record a failed request."""
        self.consecutive_failures += 1
        self.last_failure_time = time.time()
        self.total_failures += 1
        cooldown = self._get_cooldown()
        logger.warning(
            f"Circuit '{self.name}': failure #{self.consecutive_failures}, "
            f"cooldown {cooldown:.0f}s"
        )

    def get_cooldown_remaining(self) -> float:
        """Get remaining cooldown time in seconds."""
        if self.consecutive_failures == 0:
            return 0
        cooldown = self._get_cooldown()
        elapsed = time.time() - self.last_failure_time
        remaining = cooldown - elapsed
        return max(0, remaining)

    def get_status(self) -> dict:
        """Get circuit breaker status as dict."""
        return {
            "name": self.name,
            "is_open": self.is_open,
            "consecutive_failures": self.consecutive_failures,
            "total_failures": self.total_failures,
            "total_successes": self.total_successes,
            "cooldown_remaining": round(self.get_cooldown_remaining(), 1),
        }
