"""Plays a simulated portfolio frame back to the sinks, paced by a clock (spec 0011)."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Protocol

import pandas as pd

from kiozesim_tool.sink import Sample, Sink


class Clock(Protocol):
    def now(self) -> float:
        """Monotonic seconds."""
        ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class Player:
    """Sends rows to sinks. `play` may be called again with the next chunk; timing continues.

    Row `t` is due at `origin + (t - t0) / speed`, where origin/t0 are fixed at the first row ever
    played, so delays never accumulate (SINK-011). Overdue rows go out at once (SINK-015).
    """

    def __init__(self, sinks: Sequence[Sink], speed: float = 1.0, clock: Clock | None = None):
        if speed < 0:
            raise ValueError("speed must be >= 0")
        self.sinks = list(sinks)
        self.speed = speed
        self.clock: Clock = clock or SystemClock()
        self._origin: tuple[float, pd.Timestamp] | None = None

    def play(self, frame: pd.DataFrame, step: pd.Timedelta | None = None) -> None:
        """`step` is needed only when the frame has a single row."""
        frame = frame.drop(columns="total", errors="ignore").sort_index()  # SINK-010
        if step is None:
            step = pd.Timedelta(frame.index[1] - frame.index[0])
        for t, row in frame.iterrows():
            ts = pd.Timestamp(t)  # type: ignore[arg-type]
            if self.speed > 0:
                if self._origin is None:
                    self._origin = (self.clock.now(), ts)
                origin, t0 = self._origin
                due = origin + (ts - t0).total_seconds() / self.speed
                wait = due - self.clock.now()
                if wait > 0:
                    self.clock.sleep(wait)
            sample = Sample(ts, step, {str(k): float(v) for k, v in row.items()})
            for sink in self.sinks:
                sink.send(sample)
