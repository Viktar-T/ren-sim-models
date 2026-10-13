# 0018 plan: real weather

## Modules
- `kiozesim_tool/weather.py`
  - `_regrid(table, src_step, start, end, step, what)`: shared by every weather source. Checks
    `[start, end)` lies inside `[first row, last row + src_step)`, then averages (step >= src_step)
    or interpolates in time (finer step; the tail of the last period holds its value). Today's
    `FileWeatherSource.get` uses it on its tiled day.
  - `FileWeatherSource`: reads `time`; `HH:MM` → one repeated day (unchanged), full date-time →
    dated series (WX-020..022). `step` and the shape are attributes.
  - `OpenMeteoSource(params, *, fetch=None, cache_dir=None, today=None)`; params
    `OpenMeteoParams(name, latitude_deg, longitude_deg)`. Extra keyword arguments are for tests
    only; `build_source` uses the defaults.
    - Days needed: every UTC date the request touches, plus one day either side (the sunlight shift
      needs the next hour; interpolation needs neighbours). A margin day Open-Meteo does not have is
      skipped; a core day it does not have is an error (WX-005).
    - Each day goes to the Forecast API if `today-92 <= day <= today+15`, else the Historical API if
      `>= 1940-01-01`.
    - Cache: one JSON file per API, place and day,
      `<cache>/open-meteo/<api>/<lat>_<lon>/<YYYY-MM-DD>.json` (`lat`, `lon` to 4 decimals, ~10 m).
      Forecast files older than 1 hour count as missing (file time). Missing days are fetched in
      one request per contiguous run of days. Read/write failures warn once and are skipped
      (WX-012).
    - Fetch: `urllib.request` + `json`, 60 s timeout, no new dependency. An HTTP error answer's
      `reason` is passed on. All failures become `WeatherError(ValueError)` with `.box = name`.
    - Table: hourly, sunlight columns `shift(-1)` (end label → start label, WX-002); `null` → NaN.
      NaN in the rows the request uses → `WeatherError` naming the first such time.
- `kiozesim_tool/boxes.py`: `"open_meteo": OpenMeteoSource`.
- `kiozesim_tool/cli.py`: errors raised while simulating a later chunk stop the run with exit
  code 2 (WX-032), sinks closed by the existing `ExitStack`.
- `kiozesim_tool/ui/form.py`: `"online weather": ("open_meteo", {})`; `read_period(form)` →
  (from, days, errors).
- `kiozesim_tool/ui/app.py`: run index from the period; errors with a `.box` go on that box
  (WX-042). `page.html`: the two period fields beside **Run**, posted on every button.
- `examples/real_weather.yaml` (WX-031).

## Tests (no network)
A fake `fetch` builds answers of Open-Meteo's real shape from the query (values = hour number), so
the sunlight shift, seam, resampling, cache hits and limits are checked exactly. A cache-dir
fixture keeps tests out of `~/.cache`.

## Risks
- Open-Meteo's windows move with the date; `today` is injectable.
- Temperature, wind and pressure are snapshots at the full hour, used as the period's value: up to
  half an hour early, accepted (Domain notes).
