"""`kiozesim-tool` command line: `sink` (spec 0011), `ui` (spec 0017) and `size` (spec 0019)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from contextlib import ExitStack

import pandas as pd
from pydantic import ValidationError

from kiozesim import Plant
from kiozesim.plants.base import State
from kiozesim_tool import config, sizing, wiring
from kiozesim_tool.player import Clock, Player
from kiozesim_tool.sources import Source

DAY = pd.Timedelta(days=1)


def parse_step(text: str) -> pd.Timedelta:
    try:
        step = pd.Timedelta(text)
    except (ValueError, TypeError) as e:
        raise ValueError(f"invalid step {text!r}: use a pandas offset like 15min or 1h") from e
    if step <= pd.Timedelta(0) or DAY % step != pd.Timedelta(0):
        raise ValueError(f"invalid step {text!r}: must divide one day evenly")
    return step


def chunk_length(step: pd.Timedelta) -> pd.Timedelta:
    """One day, but at least two steps, so the states carried to the next chunk are exact."""
    return max(DAY, 2 * step)


def simulate_chunk(
    plants: list[Plant],  # type: ignore[type-arg]
    sources: list[Source],  # type: ignore[type-arg]
    wires: wiring.Wires,
    start: pd.Timestamp,
    end: pd.Timestamp,
    step: pd.Timedelta,
    states: dict[str, State] | None = None,
) -> tuple[pd.DataFrame, dict[str, State]]:
    """Power on `[start, end)`, plants fed by their wired sources (SINK-020, SRC-021), and the
    plants' states at `end`, to continue from (CHAIN-011)."""
    # the time grid needs >= 2 points: simulate one extra step for a one-row chunk, then drop it;
    # only the last chunk can have one row, so its (one step too late) states are never used
    index = pd.date_range(start, max(end, start + 2 * step), freq=step, inclusive="left")
    res = wiring.run(sources, plants, wires, index, states)
    return res.power[res.power.index < end], res.states


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
        names = ([s.name for s in sources], [p.name for p in plants])
        wiring.check(*names, wires, wiring.no_input(plants))  # SRC-020
        start = cfg.start if cfg.start is not None else now().floor(step)  # SINK-043
        end = cfg.end
        for name, t in (("start", start), ("end", end)):
            if t is not None and not on_grid(t, step):
                raise ValueError(f"{name} {t} is not on the {step_text} grid")
        span = chunk_length(step)
        chunk_end = start + span if end is None else min(start + span, end)
        chunk, states = simulate_chunk(plants, sources, wires, start, chunk_end, step)  # fail first
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
                    chunk_end = start + span if end is None else min(start + span, end)
                    chunk, states = simulate_chunk(
                        plants, sources, wires, start, chunk_end, step, states
                    )
            except KeyboardInterrupt:  # SINK-014: sinks are closed by the ExitStack
                pass
    # a sink could not connect or lost it for good (MQTT-011, MQTT-032), or a later chunk could not
    # be simulated, e.g. no weather past the forecast (WX-032); the sinks are closed by now
    except (ValueError, TypeError, OSError) as e:
        print(f"kiozesim-tool sink: error: {e}", file=sys.stderr)
        return 2
    return 0


def run_size(config_path: str, plant: str, want: Sequence[str]) -> int:
    """Size the chain ending at `plant` for an average output (CHAIN-042)."""
    try:
        wanted = sizing.parse_want(want)
        cfg, base = config.load(config_path)
        plants = config.build_plants(cfg.plants)
        sources = config.build_sources(cfg.sources, base)
        wires = {**config.wires_of(cfg.sources), **config.wires_of(cfg.plants)}
        res = sizing.size(plants, sources, wires, plant, wanted)
    except (ValueError, TypeError, ImportError, OSError, ValidationError) as e:
        print(f"kiozesim-tool size: error: {e}", file=sys.stderr)
        return 2
    print("\n".join(sizing.lines(res)))
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
    z = sub.add_parser("size", help="what a chain needs, on average, for an output at its end")
    z.add_argument("--config", required=True, help="YAML file with sources and plants")
    z.add_argument("--plant", required=True, help="the plant at the end of the chain")
    z.add_argument(
        "--want", required=True, action="append", help="wanted average output, e.g. heat_kw=100"
    )
    args = parser.parse_args(argv)
    if args.command == "ui":
        return run_ui(args.host, args.port)
    if args.command == "size":
        return run_size(args.config, args.plant, args.want)
    return run_sink(args.step, args.config)


if __name__ == "__main__":
    sys.exit(main())
