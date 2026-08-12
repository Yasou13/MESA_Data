import threading
import time
from dataclasses import dataclass, field


class SourceRequestBudgetExceeded(Exception):
    pass


@dataclass
class SourceRequestState:
    concurrency_limit: int = 1
    lock: threading.Lock = field(default_factory=threading.Lock)
    semaphore: threading.BoundedSemaphore = field(init=False)
    last_request_started_monotonic: float | None = None

    def __post_init__(self):
        self.semaphore = threading.BoundedSemaphore(max(1, self.concurrency_limit))


class RequestBudget:
    def __init__(self, max_requests: int):
        self.max_requests = max(1, max_requests)
        self.used_requests = 0
        self._lock = threading.Lock()

    def consume(self):
        with self._lock:
            if self.used_requests >= self.max_requests:
                raise SourceRequestBudgetExceeded(
                    f"SOURCE_REQUEST_BUDGET_EXCEEDED: Maximum request limit ({self.max_requests}) reached for this run"
                )
            self.used_requests += 1


_SOURCE_STATES: dict[str, SourceRequestState] = {}
_RUN_BUDGETS: dict[str, RequestBudget] = {}
_REGISTRY_LOCK = threading.Lock()

time_func = time.monotonic
sleep_func = time.sleep


def get_source_request_state(source_id: str, concurrency: int = 1) -> SourceRequestState:
    with _REGISTRY_LOCK:
        if source_id not in _SOURCE_STATES or _SOURCE_STATES[source_id].concurrency_limit != concurrency:
            _SOURCE_STATES[source_id] = SourceRequestState(concurrency_limit=max(1, concurrency))
        return _SOURCE_STATES[source_id]


def reset_source_states(source_id: str | None = None) -> None:
    with _REGISTRY_LOCK:
        if source_id:
            _SOURCE_STATES.pop(source_id, None)
        else:
            _SOURCE_STATES.clear()


def get_run_budget(source_id: str, max_requests: int) -> RequestBudget:
    with _REGISTRY_LOCK:
        if source_id not in _RUN_BUDGETS or _RUN_BUDGETS[source_id].max_requests != max_requests:
            _RUN_BUDGETS[source_id] = RequestBudget(max_requests)
        return _RUN_BUDGETS[source_id]


def reset_run_budget(source_id: str | None = None) -> None:
    with _REGISTRY_LOCK:
        if source_id:
            _RUN_BUDGETS.pop(source_id, None)
        else:
            _RUN_BUDGETS.clear()


def enforce_min_interval(state: SourceRequestState, min_interval_seconds: float):
    if min_interval_seconds <= 0:
        return
    with state.lock:
        now = time_func()
        if state.last_request_started_monotonic is not None:
            elapsed = now - state.last_request_started_monotonic
            if elapsed < min_interval_seconds:
                sleep_needed = min_interval_seconds - elapsed
                sleep_func(sleep_needed)
        state.last_request_started_monotonic = time_func()
