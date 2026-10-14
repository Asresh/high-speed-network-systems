"""Thread-safe, bounded event storage."""

from __future__ import annotations

from collections import deque
from threading import Lock
import time
from typing import Iterable

from .analyzer import FlowAnalyzer
from .events import RetransmitEvent


class TelemetryStore:
    def __init__(self, capacity: int = 50_000, analyzer: FlowAnalyzer | None = None) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._events: deque[RetransmitEvent] = deque(maxlen=capacity)
        self._lock = Lock()
        self._analyzer = analyzer or FlowAnalyzer()

    def add_many(self, events: Iterable[RetransmitEvent]) -> int:
        batch = list(events)
        with self._lock:
            self._events.extend(batch)
        return len(batch)

    def snapshot(self) -> list[RetransmitEvent]:
        with self._lock:
            return list(self._events)

    def summaries(self, now_ns: int | None = None) -> list[dict]:
        return self._analyzer.summarize(self.snapshot(), now_ns or time.monotonic_ns())
