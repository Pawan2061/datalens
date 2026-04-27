"""Per-step timing for the agent pipeline.

Used by ``run_agent`` to measure how long each phase of the response takes
(guardrails, schema load, planning, agent loop, synthesis, etc.) so the data
can be surfaced in the UI and exported for analysis.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator


class StepTimer:
    """Records elapsed time (ms) for named pipeline steps.

    The same step can be timed multiple times — durations are summed so a
    repeated phase (e.g. multiple ``execute_sql`` calls) yields a total.
    """

    def __init__(self) -> None:
        self._timings: dict[str, float] = {}

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._timings[name] = round(self._timings.get(name, 0.0) + elapsed_ms, 2)

    def add(self, name: str, duration_ms: float) -> None:
        """Record a duration measured externally (e.g. inside a stream)."""
        if duration_ms <= 0:
            return
        self._timings[name] = round(self._timings.get(name, 0.0) + duration_ms, 2)

    def as_dict(self) -> dict[str, float]:
        """Return a copy of the recorded timings."""
        return dict(self._timings)
