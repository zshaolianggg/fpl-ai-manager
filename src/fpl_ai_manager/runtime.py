from __future__ import annotations
from contextlib import contextmanager
from time import monotonic

class RuntimeBudget:
    def __init__(self, total_seconds: float = 1080.0):
        self.started = monotonic()
        self.total_seconds = float(total_seconds)

    @property
    def elapsed(self) -> float:
        return monotonic() - self.started

    @property
    def remaining(self) -> float:
        return max(0.0, self.total_seconds - self.elapsed)

    def can_spend(self, seconds: float, reserve: float = 120.0) -> bool:
        return self.remaining >= float(seconds) + float(reserve)

@contextmanager
def stage(name: str):
    start = monotonic()
    print(f"::notice::FPL stage start: {name}", flush=True)
    try:
        yield
    finally:
        elapsed = monotonic() - start
        print(f"::notice::FPL stage end: {name} elapsed={elapsed:.2f}s", flush=True)
