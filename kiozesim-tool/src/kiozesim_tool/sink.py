"""Sinks: destinations that simulated readings are delivered to (spec 0011).

A sink only delivers the `Sample` it is given; what to send and when is the player's job.
"""

from __future__ import annotations

import json
import sys
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType, TracebackType
from typing import Any, Self, TextIO

import pandas as pd


@dataclass(frozen=True)
class Sample:
    """One reading: period-start UTC time, step, average kW per plant, no total (SINK-001)."""

    time: pd.Timestamp
    step: pd.Timedelta
    power_kw: Mapping[str, float]

    def __post_init__(self) -> None:
        if self.time.tz is None or str(self.time.tz) != "UTC":
            raise ValueError("Sample.time must be timezone-aware UTC")
        object.__setattr__(self, "power_kw", MappingProxyType(dict(self.power_kw)))


class Sink(ABC):
    """Delivers samples somewhere (SINK-002, SINK-003). Use as a context manager."""

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> Self:
        """Build from the sink's entry in the config file (everything except `type`)."""
        if settings:
            raise ValueError(f"{cls.__name__} takes no settings, got {sorted(settings)}")
        return cls()

    def open(self) -> None:  # noqa: B027  (optional hook)
        """Connect / prepare. Default: nothing."""

    @abstractmethod
    def send(self, sample: Sample) -> None:
        """Deliver one sample. Must not simulate or wait."""

    def close(self) -> None:  # noqa: B027  (optional hook)
        """Disconnect / flush. Default: nothing."""

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class StdoutSink(Sink):
    """One JSON object per sample per line (SINK-030)."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream

    def send(self, sample: Sample) -> None:
        stream = self._stream or sys.stdout
        line = {
            "time": sample.time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "step_s": int(sample.step.total_seconds()),
            "power_kw": {k: float(v) for k, v in sample.power_kw.items()},
        }
        stream.write(json.dumps(line) + "\n")
        stream.flush()


# config `type` -> sink class (SINK-004). Later specs add their sinks here.
SINKS: dict[str, type[Sink]] = {
    "stdout": StdoutSink,
}
