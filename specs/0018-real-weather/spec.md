---
id: 0018
title: Real weather in the tool
prefix: WX
status: implemented
---

# 0018 Real weather in the tool

## Problem
Today `kiozesim-tool` only knows made-up weather: one day in a file (`HH:MM`, no date) glued onto
every date. Every day in a run looks the same, so a week in January has June sunshine and a
month-long run has no cloudy days. To see how a plant would really have done (or will do in the
next days) at a real place, the tool needs real weather: what was actually measured, or forecast,
at a given spot on given dates.

Two new ways in:
1. **Online**: ask the free Open-Meteo weather service for a place (latitude, longitude) and the run's
   dates. Works for the past and for the next days (forecast).
2. **Dated file**: a CSV of real weather with full dates and times, e.g. exported from a weather
   station, for when you have your own measurements or no internet.

Both are new source types (spec 0016) in the `sink` config and on the web page.

## Scope
In:
- `kiozesim_tool.weather.OpenMeteoSource`: weather for a place and the requested time steps, from
  Open-Meteo, past and forecast.
- A disk cache so the same place and dates are not downloaded again.
- Dated weather CSV files: `weather_file` learns a second file shape, for the `sink` config.
- Source type `open_meteo` in the `sink` config; a source box `online weather` on the web page.
- A run period on the web page (today the page always runs 2026-06-21).
- The made-up repeating day stays: `weather_file` with an `HH:MM` file and the page's
  `sample weather` keep working exactly as today.

Out:
- Other weather services (PVGIS, DWD, national services, paid APIs).
- Weather inside the library: fetching stays in the app (SRC-012, constitution 14).
- Sub-hourly online weather (Open-Meteo's 15-minute data exists only in some regions); finer steps
  are interpolated from hourly as the file source already does.
- Picking the place on a map.
- Uploading a dated weather file on the web page (`sink` only for now).

## Domain notes
- **Open-Meteo** (open-meteo.com): free weather service, no account or key. Free use is limited to
  non-commercial use (this is a university project, so that fits) and about 10 000 requests a
  day. It offers two parts we need:
  - *Forecast API* (`api.open-meteo.com/v1/forecast`): from 92 days back up to 16 days ahead
    (today and the 15 days after it).
  - *Historical API* (`archive-api.open-meteo.com/v1/archive`): re-computed past weather ("reanalysis",
    ERA5) from 1940 until about 5 days ago. Reanalysis is a weather model fed with all past
    measurements, so it gives values everywhere, not only where a station stands.
  The source asks the Forecast API for every day it covers (its recent past days are the freshest
  data) and the Historical API for the older days, and stitches them together.
- **Which Open-Meteo values map to which of our columns** (hourly, `timezone=UTC`,
  `wind_speed_unit=ms`):

  | Our column | Open-Meteo variable | Meaning |
  |---|---|---|
  | `ghi_w_m2` | `shortwave_radiation` | all sunlight on flat ground |
  | `dni_w_m2` | `direct_normal_irradiance` | sunlight straight from the sun's disc, on a surface facing the sun |
  | `dhi_w_m2` | `diffuse_radiation` | sunlight scattered by sky and clouds, on flat ground |
  | `temp_air_c` | `temperature_2m` | air temperature 2 m above ground |
  | `wind_speed_m_s` | `wind_speed_10m` | wind 10 m above ground (the height PV and turbines assume for the input) |
  | `pressure_hpa` | `surface_pressure` | air pressure at the ground (not the sea-level one) |

- **Labels, the tricky bit**: Open-Meteo labels a sunlight value with the *end* of the hour it
  averages ("13:00" = sunlight from 12:00 to 13:00). Our time grid labels a period by its *start*
  (constitution 3). So sunlight values are moved back one hour. Temperature, wind and pressure are
  snapshots at the full hour and are kept as they are.
- **Dated file**: like the one-day file, but the `time` column holds full date-times
  (`2024-06-01T13:00`, UTC unless a zone like `+02:00` is written). Each row is the period starting
  at that time, all rows one step apart.
- **Cache**: a folder of downloaded answers. Past weather does not change, so it can be kept for
  ever; a forecast gets better every few hours, so it is re-downloaded when older than 1 hour.

## Requirements

Online weather
- **WX-001** `kiozesim_tool.weather.OpenMeteoSource` MUST be a `Source` with no inputs, params
  `name`, `latitude_deg` (−90..90) and `longitude_deg` (−180..180), and outputs `ghi_w_m2`,
  `dni_w_m2`, `dhi_w_m2`, `temp_air_c`, `wind_speed_m_s` and `pressure_hpa` on exactly the requested
  index.
- **WX-002** It MUST request hourly data in UTC with wind in m/s, map the variables as in the
  Domain notes table, and move the sunlight columns back one hour so every row is labelled by its
  period start.
- **WX-003** It MUST fetch days from 92 days before today (UTC) to 15 days after it from the Forecast
  API and older days from the Historical API, and MUST return one gap-free table across the seam.
- **WX-004** For a step longer than one hour it MUST average; for a shorter step it MUST interpolate
  in time, as `FileWeatherSource` does (SINK-044 rules via SRC-011).
- **WX-005** A request outside what Open-Meteo has (before 1940-01-01, after the forecast's last day,
  or values missing in the answer) MUST raise an error naming the source and the first time it
  cannot cover.
- **WX-006** A network failure or an error answer from Open-Meteo MUST raise an error naming the
  source and the reason, never return made-up or partial data.
- **WX-007** The source MUST NOT reach the network when built, only when asked for data, and tests
  MUST run without network (the HTTP call is injectable).

Cache
- **WX-010** Downloaded answers MUST be stored on disk under the user's cache folder
  (`$XDG_CACHE_HOME/kiozesim-tool/open-meteo/`, default `~/.cache/...`) keyed by place, dates and
  API; a later request fully covered by the cache MUST NOT reach the network.
- **WX-011** Cached Historical API answers MUST be kept without expiry; cached Forecast API answers
  MUST be re-downloaded once older than 1 hour.
- **WX-012** A cache that cannot be read or written MUST NOT stop a run: the source falls back to
  downloading, and warns once.

Dated file
- **WX-020** `weather_file` MUST keep reading `HH:MM` one-day files as today (SRC-011); a weather
  file whose `time` column holds full date-times MUST be read as a dated series:
  times without a zone are UTC, rows MUST be increasing with one regular step and no empty values.
- **WX-021** A dated file asked for times outside its first row's start and last row's end MUST
  raise an error naming the file and the first missing time; it MUST NOT repeat or invent data.
- **WX-022** A dated file MUST be averaged or interpolated to the requested step by the same rules as
  WX-004.

Tool config (`sink`)
- **WX-030** `sources:` MUST accept `type: open_meteo` with `name`, `latitude_deg`, `longitude_deg`;
  source types become `weather_file`, `open_meteo`, `constant` and `digester` (changes SRC-030).
- **WX-031** `kiozesim-tool/examples/` MUST hold `real_weather.yaml`: the plants of `sink.yaml` wired
  to an `open_meteo` source for Warsaw (52.23, 21.01) over a fixed past week, at `speed: 0`.
- **WX-032** When weather cannot be had for a later part of a run (e.g. a run without `end:` going
  past the forecast's last day, or the network gone), `sink` MUST stop with exit code 2 and an
  error message naming the source, after closing its sinks.

Web page
- **WX-040** The page MUST offer an `online weather` source box with latitude and longitude fields
  (changes SRC-040).
- **WX-041** The page MUST have a **from** date (default 2026-06-21) and a **days** number (1–31,
  default 1) next to **Run**; the run covers those days hourly in UTC, and both values MUST be kept
  across every button. An invalid value MUST be shown next to its field and nothing run.
- **WX-042** A failed download MUST be shown as an error on that source box (UI-018), and the rest
  of the page MUST keep the user's inputs.
- **WX-043** `sample weather` MUST stay offered and stay the first page's source (SRC-044); on a
  run period of several days it repeats its day on every date.

## Acceptance
- With a fake Open-Meteo answer of the real shape (no network), the source returns the expected
  columns on a 15-minute and a 1-day index, sunlight shifted by one hour.
- A run of `real_weather.yaml` against live Open-Meteo gives a PV yield for the chosen June week in
  Warsaw within ±25 % of PVGIS's estimate for the same system and month (checked by hand once, not
  in the test suite, since it needs the internet).
- Second run of the same config makes no network request (cache).

## Open questions
- [x] **1. Web page run period**: **from** date and **days** (1–31) next to **Run** (WX-041).
- [x] **2. `sink` past the forecast's end**: stops with a clear error (WX-005, WX-032).
- [x] **3. Forecast expiry in the cache**: 1 hour (WX-011).
- [x] **4. Dated file**: same `weather_file` type, shape told by the `time` column (WX-020).
- [x] **5. Dated file on the web page**: not now, `sink` only (Scope).
- [x] **6. Licence**: university project, non-commercial; the free tier fits.

## Changelog
- 2026-10-13 created (draft): Open-Meteo online source (past + forecast), disk cache, dated weather
  files, `sink` config and web page
- 2026-10-13 open questions resolved with the proposed defaults; repeating sample day kept (WX-043,
  WX-020); `sink` stops cleanly on missing weather (WX-032); Forecast API window checked against the
  live service (92 days back, 15 ahead); approved
- 2026-10-13 implemented. Hand check (Acceptance): `real_weather.yaml` live, 1-8 June 2025, PV
  `roof` 141.0 kWh vs PVGIS 5.2 typical June week 137.8 kWh (+2 %, within ±25 %)
