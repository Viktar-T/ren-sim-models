"""`kiozesim-tool` command line (spec 0011)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from contextlib import ExitStack

import pandas as pd
from pydantic import ValidationError

from kiozesim import Plant, Portfolio, TimeSeries
from kiozesim_tool import config
from kiozesim_tool.player import Clock, Player
from kiozesim_tool.weather import DAY, WeatherSource


def parse_step(text: str) -> pd.Timedelta:
    try:
        step = pd.Timedelta(text)
    except (ValueError, TypeError) as e:
        raise ValueError(f"invalid step {text!r}: use a pandas offset like 15min or 1h") from e
    if step <= pd.Timedelta(0) or DAY % step != pd.Timedelta(0):
        raise ValueError(f"invalid step {text!r}: must divide one day evenly")
    return step


def simulate_chunk(
    plants: list[Plant],  # type: ignore[type-arg]
    weather: WeatherSource,
    start: pd.Timestamp,
    end: pd.Timestamp,
    step: pd.Timedelta,
) -> pd.DataFrame:
    """Portfolio output on `[start, end)` (SINK-020)."""
    # the time grid needs >= 2 points: simulate one extra step for a one-row chunk, then drop it
    frame = weather.get(start, max(end, start + 2 * step), step)
    inputs: dict[str, TimeSeries] = {
        p.name: p.inputs_model.from_frame(frame) for p in plants if p.inputs_model is not None
    }
    out = Portfolio(plants).simulate(inputs)
    return out[out.index < end]


def on_grid(t: pd.Timestamp, step: pd.Timedelta) -> bool:
    return t.floor(step) == t


def run_sink(
    step_text: str,
    config_path: str,
    *,
    clock: Clock | None = None,
    now: Callable[[], pd.Timestamp] = lambda: pd.Timestamp.now(tz="UTC"),
    max_chunks: int | None = None,
) -> int:
    try:
        step = parse_step(step_text)
        cfg, base = config.load(config_path)
        plants = config.build_plants(cfg.plants)
        sinks = config.build_sinks(cfg.sinks)
        weather = config.build_weather(cfg.weather, base)
        start = cfg.start if cfg.start is not None else now().floor(step)  # SINK-043
        end = cfg.end
        for name, t in (("start", start), ("end", end)):
            if t is not None and not on_grid(t, step):
                raise ValueError(f"{name} {t} is not on the {step_text} grid")
        chunk_end = start + DAY if end is None else min(start + DAY, end)
        chunk = simulate_chunk(plants, weather, start, chunk_end, step)  # fail before sending
    except (ValueError, TypeError, ImportError, OSError, ValidationError) as e:
        print(f"kiozesim-tool sink: error: {e}", file=sys.stderr)
        return 2

    with ExitStack() as stack:
        for s in sinks:
            stack.enter_context(s)
        player = Player(sinks, cfg.speed, clock)
        n = 0
        try:
            while True:
                player.play(chunk, step)
                n += 1
                start = chunk_end
                if (max_chunks is not None and n >= max_chunks) or start == end:
                    break
                chunk_end = start + DAY if end is None else min(start + DAY, end)
                chunk = simulate_chunk(plants, weather, start, chunk_end, step)
        except KeyboardInterrupt:  # SINK-014: sinks are closed by the ExitStack
            pass
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kiozesim-tool")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("sink", help="simulate plants and stream the readings to sinks")
    p.add_argument("step", help="time step of the readings, e.g. 15min or 1h")
    p.add_argument("--config", required=True, help="YAML file with plants, weather and sinks")
    args = parser.parse_args(argv)
    return run_sink(args.step, args.config)


if __name__ == "__main__":
    sys.exit(main())
