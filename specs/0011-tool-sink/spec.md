---
id: 0011
title: Tool sink command
prefix: SINK
status: implemented
---

# 0011 Tool sink command

## Problem
The library computes how much power plants produce, but only inside Python. To test other systems
(dashboards, controllers, energy-management software) people need those numbers to *arrive* the way a
real plant's meter readings would: one reading at a time, as time passes, over a channel such as an
MQTT broker or a Kafka topic.

`kiozesim-tool sink` pretends to be a live plant (or a group of plants): it simulates the output, then
plays it back reading by reading and pushes each reading to one or more destinations ("sinks").

This is the first of several `kiozesim-tool` specs. It sets up the command, the `Sink` interface and
the playback loop, with one simple sink. Real network sinks (MQTT, Kafka, ...) come in their own specs
and only have to implement the interface defined here.

## Scope
In:
- The `kiozesim-tool sink` command and its options.
- The `Sink` interface (abstract class) in `kiozesim_tool`.
- The playback loop ("player") that walks through the simulated output and hands each reading to
  the sinks at the right moment.
- Weather as a source from `kiozesim_utils` (spec 0016); the one-day file source moved there.
- One sink: `stdout` (prints JSON lines), useful on its own and for testing.
- A YAML config file describing plants and sinks.

Out:
- MQTT, Kafka and other network sinks (one later spec each).
- Weather sources other than the one-day file (live feeds, APIs): later specs.
- Command-line options beyond `<step>` and `--config` (no `--loop`, `--now`, `--weather`, ...).
- Any change to how the library simulates.
- Receiving commands back from the environment (e.g. a controller switching a plant off).

## Domain notes
- *Sink*: a destination that readings flow into, like water into a sink. An MQTT broker, a Kafka topic,
  a file or the terminal can all be sinks.
- *MQTT / Kafka*: two common "post office" systems for machines. A sender publishes messages to a
  named channel (MQTT calls it a *topic*, Kafka too); anyone subscribed to that channel receives them.
  Real plants and smart meters often report this way.
- *Reading* (here called a `Sample`): the values for one time step: the timestamp, the power of each
  plant, in kW. No total is sent: the receiver can add the plants up itself. Power is the average over the step (constitution 9).
- *Step*: the spacing of readings in simulated time, e.g. `15min` or `1h`.
- *Real time / playback speed*: with speed 1, a reading for a 15-minute step is sent every 15 real
  minutes, like a real meter. With speed 60, an hour of simulated time passes in one real minute.
  Speed 0 (or "as fast as possible") sends everything immediately, handy for filling a database.
- *Weather source*: where the weather comes from. Today a file holding exactly one day of times
  without a date ("an opaque day", e.g. `00:00`, `00:15`, ...). The source glues those times onto
  the real current date; when
  playback runs past midnight the next day starts and the same file is read again, so the "plant"
  runs forever on a repeating day.
- *Delivery delay*: if a reading for 10:00 is sent at 10:00 but the MQTT broker gets it at 10:03,
  nothing is lost or wrong: the reading carries its own timestamp (`time`, 10:00) inside the message,
  so the receiver files it under 10:00, not 10:03. Like a letter with the date written inside, it
  does not matter when the post arrives. The player also plans each send against the clock from the
  start (SINK-011), so a slow send never pushes later readings later. If a send is so slow that the
  next reading is already due, the next one goes out straight away; readings are never skipped.
- *Time range*: `start:` and `end:` in the config choose which simulated period is played, e.g. one
  week in January. The weather file's day is glued onto every date in the range. Without a range the
  tool plays from "now" for ever. A range in the past at `speed: 0` fills a database with history in
  seconds; the same range at `speed: 1` replays it at the real pace.
- *Why the sink does not own the portfolio*: the sink only knows *how to deliver* a reading; the
  player knows *what* to send and *when*. This way one simulation can feed several sinks at once
  (e.g. MQTT and a log file), each sink is tiny and easy to test, and new sinks never touch
  simulation or timing code.

```
WeatherSource ─► Portfolio.simulate ─► DataFrame ─► Player (clock, speed) ─► Sample ─► Sink 1 (stdout)
                                                                                  └─► Sink 2 (mqtt, later)
```

## Requirements

### Interface
- **SINK-001** `kiozesim_tool.sink` MUST define a frozen `Sample` with `time` (tz-aware UTC timestamp,
  period start), `step` (a `pd.Timedelta`) and `power_kw` (mapping of plant name to kW, one entry per
  plant, no `total`).
- **SINK-002** `kiozesim_tool.sink` MUST define an abstract `Sink` with `open()`, `send(sample)` and
  `close()`, and be usable as a context manager (`open` on enter, `close` on exit, also on error).
- **SINK-003** A `Sink` MUST NOT simulate or wait; it only delivers the `Sample` it is given.
- **SINK-004** Sinks MUST be registered by name in a `SINKS` registry so the command can select them
  by name and later specs add new ones without changing the command or the player.

### Player
- **SINK-010** The player MUST take a simulated portfolio frame (one column per plant plus `total`,
  CORE-005), drop `total`, and send each row, in time order, to every sink as one `Sample`.
- **SINK-011** With speed `s > 0`, the player MUST send row `i` no earlier than
  `start + i * step / s` in wall-clock time, without drift accumulating over many rows.
- **SINK-012** With speed `0`, the player MUST send all rows without waiting.
- **SINK-013** The clock MUST be injectable so tests run without real waiting.
- **SINK-015** When sending falls behind (a reading is already overdue), the player MUST send the
  overdue readings at once, in order, and MUST NOT skip any.
- **SINK-014** On Ctrl+C the player MUST stop sending, close every sink and exit with code 0.

### Weather source
SINK-040, SINK-041, SINK-042 and SINK-044 are retired: the one-day file source and its rules moved
to `kiozesim_utils.FileWeatherSource` (SRC-011): a CSV of times of day (`HH:MM`, UTC, no date)
covering exactly one day on a regular step, repeated on every date, averaged to a coarser step or
linearly interpolated to a finer one.
- **SINK-043** Without `start:` in the config, playback MUST start at the current UTC time rounded
  down to `<step>`; at speed 1 the sample timestamps therefore match the wall clock.

### Command
- **SINK-020** `kiozesim-tool sink <step> [options]` MUST simulate the configured plants, fed by their
  wired sources on the `<step>` grid (a pandas offset such as `15min`, `1h`) and play the result back.
- **SINK-021** `--config FILE` MUST give a YAML file with `sources:` (SRC-030), `plants:` (type,
  name, `from`, datasheet, params) and `sinks:` (one or more
  sinks by registry name, each with its own settings). It is the only option besides `<step>`.
- **SINK-022** Playback speed MUST be `speed:` in the config file (default `1`, real time). The CLI
  MUST use `argparse` (no new dependency).
- **SINK-023** An invalid config file, invalid plant options, an unknown sink name or an invalid step
  MUST fail with a clear message and a non-zero exit code before anything is sent.
- **SINK-024** The config MAY give a time range `start:` / `end:` (ISO 8601 date-times; no time zone
  means UTC). Playback MUST then cover exactly `[start, end)`: readings from `start` up to but not
  including `end`, then the command exits with code 0. Without `end:` playback runs until Ctrl+C.
  `start` and `end` MUST lie on the `<step>` grid and `end` MUST be later than `start`.
- **SINK-025** `speed: 0` without `end:` MUST be rejected (it would flood the sinks without end).
- **SINK-026** Every plant type whose spec is `implemented` MUST be usable in `plants:`; the tool MUST
  install the engines those types need (`kiozesim[pv,wind]`).

### Examples
- **SINK-045** `kiozesim-tool/examples/day_weather.csv` MUST hold every column any implemented plant
  type requires (today `ghi_w_m2`, `temp_air_c`, `wind_speed_m_s` at 10 m, `pressure_hpa`), the
  same made-up breezy day as the web UI's sample weather (UI-011).
- **SINK-046** `kiozesim-tool/examples/sink.yaml` MUST contain one plant of each implemented type
  (today a PV roof, a wind turbine, a vertical-axis turbine and a gas engine on a digester) and MUST run without error at
  `speed: 0` over its time range.

### stdout sink
- **SINK-030** The `stdout` sink MUST print one JSON object per sample per line:
  `{"time": "<ISO 8601 UTC>", "step_s": <seconds>, "power_kw": {"<plant>": <kW>, ...}}`.

## Acceptance
Unit tests with a fake clock cover the player; a CLI test runs `kiozesim-tool sink 1h --config ...` with `speed: 0`
and checks the JSON lines on stdout. `scripts/spec_check.py` is green.

## Open questions
None.

## Changelog
- 2026-10-07 created (draft)
- 2026-10-07 weather source (repeating one-day file), config file for plants/sinks/speed, no extra
  options, delivery delay explained, SINK-015
- 2026-10-07 open questions resolved (dateless one-day file glued to the current date, start at now
  rounded to step, resample mean/interpolate, speed in config, argparse); SINK-043, SINK-044; approved
- 2026-10-07 implemented
- 2026-10-07 optional `start`/`end` time range (SINK-024), `speed: 0` needs `end` (SINK-025)
- 2026-10-07 `total` no longer sent (SINK-001, SINK-010, SINK-030): receivers add plants up
- 2026-10-08 HAWT support: SINK-026 (all implemented types, `kiozesim[pv,wind]`), SINK-045
  (example weather columns, breezy day), SINK-046 (`sink.yaml` with a turbine); back to draft
- 2026-10-08 approved
- 2026-10-08 HAWT support implemented
- 2026-10-09 VAWT support (spec 0004): SINK-046 example gains a VAWT; no other change (VAWT needs
  no extra engine)
- 2026-10-12 sources and wiring (0016): `sources:` replaces `weather:` (SINK-021), plants fed by
  wired sources (SINK-020); SINK-040..042 and SINK-044 retired, moved to SRC-011 in `kiozesim_utils`
