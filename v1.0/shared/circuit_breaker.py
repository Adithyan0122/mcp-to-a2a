"""
Circuit Breaker — Supply Chain v1.0
Prevents cascading failures when downstream agents are unavailable.
States: CLOSED (normal) → OPEN (failing, reject calls) → HALF_OPEN (testing recovery)
"""

import time
import threading
import logging
from enum import Enum
from typing import Any, Callable

log = logging.getLogger("circuit-breaker")


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    Circuit breaker for inter-agent calls.
    - CLOSED: Normal operation, calls pass through
    - OPEN: Too many failures, calls are rejected immediately
    - HALF_OPEN: Testing if service recovered, one call allowed through
    """

    def __init__(self, name: str, failure_threshold: int = 3, timeout: int = 60):
        self.name = name
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0
        self.success_count = 0
        self._lock = threading.Lock()

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function through the circuit breaker.
        Raises CircuitOpenError if circuit is open.
        """
        with self._lock:
            if self.state == CircuitState.OPEN:
                if time.time() - self.last_failure_time >= self.timeout:
                    log.info(f"[{self.name}] Circuit HALF_OPEN — testing recovery")
                    self.state = CircuitState.HALF_OPEN
                else:
                    remaining = self.timeout - (time.time() - self.last_failure_time)
                    log.warning(f"[{self.name}] Circuit OPEN — rejecting call ({remaining:.0f}s until retry)")
                    raise CircuitOpenError(
                        f"Circuit breaker '{self.name}' is OPEN. "
                        f"Too many failures ({self.failure_count}). "
                        f"Retry in {remaining:.0f}s."
                    )

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                log.info(f"[{self.name}] Circuit CLOSED — recovery confirmed")
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.success_count = 0
            self.success_count += 1

    def _on_failure(self):
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.state == CircuitState.HALF_OPEN:
                log.warning(f"[{self.name}] Circuit OPEN — recovery failed")
                self.state = CircuitState.OPEN
            elif self.failure_count >= self.failure_threshold:
                log.warning(f"[{self.name}] Circuit OPEN — threshold reached ({self.failure_count} failures)")
                self.state = CircuitState.OPEN

    def get_status(self) -> dict:
        """Get current circuit breaker status for health reporting."""
        with self._lock:
            return {
                "name": self.name,
                "state": self.state.value,
                "failure_count": self.failure_count,
                "failure_threshold": self.failure_threshold,
                "timeout_s": self.timeout,
                "last_failure": self.last_failure_time,
                "success_count": self.success_count,
            }

    def reset(self):
        """Manually reset the circuit breaker."""
        with self._lock:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            log.info(f"[{self.name}] Circuit manually reset to CLOSED")


class CircuitOpenError(Exception):
    """Raised when a circuit breaker is open and rejecting calls."""
    pass


# ── Global Circuit Breaker Registry ───────────────────────────────────────────

_breakers: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_breaker(name: str, failure_threshold: int = 3, timeout: int = 60) -> CircuitBreaker:
    """Get or create a named circuit breaker."""
    with _registry_lock:
        if name not in _breakers:
            _breakers[name] = CircuitBreaker(name, failure_threshold, timeout)
        return _breakers[name]


def get_all_breaker_status() -> list[dict]:
    """Get status of all registered circuit breakers."""
    with _registry_lock:
        return [b.get_status() for b in _breakers.values()]
