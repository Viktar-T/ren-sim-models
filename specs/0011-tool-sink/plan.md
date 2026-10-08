# 0011 plan

## Modules (`kiozesim-tool/src/kiozesim_tool/`)
- `sink.py`: `Sample` (frozen dataclass), `Sink` ABC (`open`/`send`/`close`, context manager),
  `StdoutSink`, `SINKS` registry. A sink class is built from its config entry via
  `Sink.from_settings(settings: dict)`; each sink validates its own settings (stdout takes none), so
  later sinks (MQTT, Kafka) add only a class and a registry line.
- `weather.py`: `WeatherSource` ABC with `get(start, end, step) -> DataFrame` on `[start, end)`.
  `FileWeatherSource(path)` reads the dateless day once, lays it over every date from the day before
  `start` to the day after `end` (so averaging/interpolation across midnight wraps around), resamples
  (mean when coarser, linear interpolation when finer) and slices.
- `player.py`: `Clock` protocol (`now()` monotonic seconds, `sleep(s)`), `SystemClock`, `Player`.
  `Player.play(frame)` can be called repeatedly with consecutive chunks; the wall-clock origin is fixed
  at the first row ever sent, row `t` is due at `origin + (t - t0) / speed`. No drift, overdue rows go
  out immediately.
- `config.py`: pydantic `Config` (`speed`, `plants`, `weather`, `sinks`, `extra="forbid"`) and
  `build_plants`: plant entries are `{type, name, datasheet: <bundled name>, ...params}`; any
  `Datasheet`-typed field given as a string is loaded with `bundled()`. Relative weather paths resolve
  against the config file's folder.
- `cli.py`: `argparse`, `kiozesim-tool sink <step> --config FILE`. Validates everything, then loops:
  fetch one day of weather from the current chunk start, simulate the portfolio, play it, advance.
  `KeyboardInterrupt` -> sinks closed by `ExitStack`, exit 0. Errors -> message on stderr, exit 2.

## Packaging
- `pyproject.toml`: depends on `kiozesim[pv]`; script `kiozesim-tool = "kiozesim_tool.cli:main"`.
- `kiozesim-tool/examples/`: `sink.yaml` and `day_weather.csv` (dateless copy of
  `kiozesim/examples/pv_weather.csv`) so the command can be tried right away.

## Tests (`kiozesim-tool/tests/test_sink.py`, no `__init__.py`)
Fake clock for the player; temp CSV/YAML for weather and config; `main([...])` with `speed: 0` and a
patched chunk limit for the CLI.

## Risks
- The command runs forever by design; the CLI loop takes an internal `max_chunks` used only by tests.
- PV refuses steps > 1 h (PV-spec); that surfaces as a normal config error before sending.

## HAWT support (2026-10-08, SINK-026, SINK-045, SINK-046)
- No code change in the command: `config.build_plants` already takes any registered type and
  loads a datasheet given by name through `bundled()`, which now includes the turbine library.
- `pyproject.toml`: `kiozesim[pv,wind]`.
- `examples/day_weather.csv`: the web UI's sample day without dates (same values, `HH:MM`).
- `examples/sink.yaml`: adds a turbine (`E-82/2300`, hub 108 m) next to the PV roof.
- Tests: a config with one plant of each implemented type runs (SINK-026); the example weather has
  the columns and matches the UI sample (SINK-045); `sink.yaml` runs at speed 0 over its range
  (SINK-046). Implemented types are read from spec front matter, as in the UI tests.
