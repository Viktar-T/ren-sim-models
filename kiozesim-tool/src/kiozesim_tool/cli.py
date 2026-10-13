"""`kiozesim-tool` command line: `sink` (spec 0011) and `ui` (spec 0017)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from contextlib import ExitStack

import pandas as pd
from pydantic import ValidationError

from kiozesim import Plant, Source
from kiozesim_tool import config, wiring
from kiozesim_tool.player import Clock, Player

DAY = pd.Timedelta(days=1)


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
    sources: list[Source],  # type: ignore[type-arg]
    wires: wiring.Wires,
    start: pd.Timestamp,
    end: pd.Timestamp,
    step: pd.Timedelta,
) -> pd.DataFrame:
    """Portfolio output on `[start, end)`, plants fed by their wired sources (SINK-020, SRC-021)."""
    # the time grid needs >= 2 points: simulate one extra step for a one-row chunk, then drop it
    index = pd.date_range(start, max(end, start + 2 * step), freq=step, inclusive="left")
    out = wiring.run(sources, plants, wires, index)
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
        sources = config.build_sources(cfg.sources, base)
        wires = {**config.wires_of(cfg.sources), **config.wires_of(cfg.plants)}
        wiring.check([s.name for s in sources], [p.name for p in plants], wires)  # SRC-020
        start = cfg.start if cfg.start is not None else now().floor(step)  # SINK-043
        end = cfg.end
        for name, t in (("start", start), ("end", end)):
            if t is not None and not on_grid(t, step):
                raise ValueError(f"{name} {t} is not on the {step_text} grid")
        chunk_end = start + DAY if end is None else min(start + DAY, end)
        chunk = simulate_chunk(plants, sources, wires, start, chunk_end, step)  # fail first
    except (ValueError, TypeError, ImportError, OSError, ValidationError) as e:
        print(f"kiozesim-tool sink: error: {e}", file=sys.stderr)
        return 2

    try:
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
                    chunk = simulate_chunk(plants, sources, wires, start, chunk_end, step)
            except KeyboardInterrupt:  # SINK-014: sinks are closed by the ExitStack
                pass
    # a sink could not connect or lost it for good (MQTT-011, MQTT-032), or a later chunk could not
    # be simulated, e.g. no weather past the forecast (WX-032); the sinks are closed by now
    except (ValueError, TypeError, OSError) as e:
        print(f"kiozesim-tool sink: error: {e}", file=sys.stderr)
        return 2
    return 0


def run_ui(host: str, port: int) -> int:
    """Start the web UI (APP-003); imported here so `sink` does not load the web stack."""
    import uvicorn

    from kiozesim_tool.ui.app import app

    uvicorn.run(app, host=host, port=port)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kiozesim-tool")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("sink", help="simulate plants and stream the readings to sinks")
    p.add_argument("step", help="time step of the readings, e.g. 15min or 1h")
    p.add_argument("--config", required=True, help="YAML file with sources, plants and sinks")
    u = sub.add_parser("ui", help="start the web UI")
    u.add_argument("--host", default="127.0.0.1")
    u.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if args.command == "ui":
        return run_ui(args.host, args.port)
    return run_sink(args.step, args.config)


if __name__ == "__main__":
    sys.exit(main())
