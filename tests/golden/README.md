# Golden datasets

One directory per case: `tests/golden/<plant>/<case>/` where `<plant>` is a key of
`kioze_sim.plants.REGISTRY`.

```
case.yaml      params: {...}        # PlantParams fields, except the datasheet
               inputs: {...}        # optional extra kwargs for the Inputs model
               datasheet: file.yaml # path relative to the case dir, or a bundled datasheet name (Datasheet.available())
               rtol: 0.02           # relative tolerance
               atol: 0.1            # absolute tolerance in kW (kWh for expected_energy_kwh)
               expected_energy_kwh: 4200.0  # optional: compare total energy over inputs.csv
                                            # instead of expected.csv (e.g. annual yield)
               source: "where the reference numbers come from"
inputs.csv     index column `time` (ISO, UTC) + the columns the plant's Inputs model reads
               (the fields of the plant's TimeSeries struct, e.g. `ghi_w_m2`, `wind_speed_m_s`, `heat_demand_kw`)
expected.csv   columns `time`, `power_kw`
               (plants that take no input: no CSVs, put `expected_power_kw: <float>` in case.yaml)
```

Golden values must come from an independent reference (measurement, published dataset, or an
established library run), never from this library's own output. A case whose plant still raises
`NotImplementedError` is reported as xfail.
