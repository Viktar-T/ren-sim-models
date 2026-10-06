import inspect

import pandas as pd
import pytest
from pydantic import ValidationError

from kiozesim import Plant, PlantOutput, PlantParams, Portfolio, TimeSeries
from kiozesim.timegrid import TimeGridError, validate_time_index


class ConstParams(PlantParams):
    kw: float


class SteadyPlant(Plant[ConstParams, None, PlantOutput]):
    """Takes no input."""

    params_model = ConstParams

    def _simulate(self, ts: None) -> PlantOutput:
        return PlantOutput(power_kw=self.params.kw)


class WindInputs(TimeSeries):
    wind_speed: pd.Series
    temp_air: pd.Series


class LinearPlant(Plant[ConstParams, WindInputs, PlantOutput]):
    """kW = params.kw * wind_speed."""

    params_model = ConstParams
    inputs_model = WindInputs

    def _simulate(self, ts: WindInputs) -> PlantOutput:
        return PlantOutput(power_kw=ts.wind_speed * self.params.kw)


class WrongIndexPlant(LinearPlant):
    def _simulate(self, ts: WindInputs) -> PlantOutput:
        return PlantOutput(power_kw=pd.Series(1.0, index=ts.index[:-1]))


@pytest.fixture
def idx() -> pd.DatetimeIndex:
    return pd.date_range("2025-01-01", periods=24, freq="h", tz="UTC")


@pytest.fixture
def wind(idx) -> WindInputs:
    return WindInputs(wind_speed=pd.Series(5.0, index=idx), temp_air=pd.Series(10.0, index=idx))


@pytest.mark.spec("CORE-001")
def test_plant_is_abstract():
    with pytest.raises(TypeError):
        Plant(PlantParams(name="x"))  # type: ignore[abstract]


@pytest.mark.spec("CORE-001")
def test_contract_takes_at_most_one_optional_argument():
    sig = inspect.signature(Plant.simulate)
    assert list(sig.parameters) == ["self", "ts"]
    assert sig.parameters["ts"].default is None


@pytest.mark.spec("CORE-002")
@pytest.mark.parametrize(
    "mutate",
    [
        lambda i: i.tz_localize(None),
        lambda i: i[[0, 1, 3]],
        lambda i: i[::-1],
        lambda i: i[:1],
        lambda i: i.tz_convert("Europe/Warsaw"),
    ],
)
def test_invalid_time_index_rejected(idx, mutate):
    with pytest.raises(TimeGridError):
        validate_time_index(mutate(idx))
    s = pd.Series(1.0, index=mutate(idx))
    with pytest.raises(ValidationError):
        WindInputs(wind_speed=s, temp_air=s)


@pytest.mark.spec("CORE-002")
def test_series_in_one_struct_must_share_an_index(idx):
    hourly = pd.Series(1.0, index=idx)
    fine = pd.Series(1.0, index=pd.date_range(idx[0], periods=24 * 12, freq="5min", tz="UTC"))
    with pytest.raises(ValidationError, match="index differs"):
        WindInputs(wind_speed=hourly, temp_air=fine)
    with pytest.raises(ValidationError, match="NaN"):
        WindInputs(wind_speed=hourly.where(hourly < 0), temp_air=hourly)


@pytest.mark.spec("CORE-003")
def test_params_are_frozen_and_strict():
    p = ConstParams(name="a", kw=1.0)
    with pytest.raises(ValidationError):
        p.kw = 2.0  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ConstParams(name="a", kw=1.0, typo=3)  # type: ignore[call-arg]


@pytest.mark.spec("CORE-004")
def test_timeseries_plant_output(wind):
    out = LinearPlant(ConstParams(name="a", kw=2.0)).simulate(wind)
    assert out.power_kw.name == "power_kw" and (out.power_kw == 10.0).all()
    assert out.power_kw.index.equals(wind.index)


@pytest.mark.spec("CORE-004")
def test_no_input_plant_returns_scalar():
    out = SteadyPlant(ConstParams(name="s", kw=7.0)).simulate()
    assert out.power_kw == 7.0


@pytest.mark.spec("CORE-004")
def test_bad_output_and_bad_call_rejected(wind):
    with pytest.raises(ValidationError):
        PlantOutput(power_kw=pd.Series([-1.0, 1.0]))
    with pytest.raises(ValidationError):
        PlantOutput(power_kw=float("nan"))
    p = ConstParams(name="b", kw=1.0)
    with pytest.raises(ValueError):
        WrongIndexPlant(p).simulate(wind)
    with pytest.raises(TypeError):
        LinearPlant(p).simulate()  # missing the struct
    with pytest.raises(TypeError):
        SteadyPlant(p).simulate(wind)  # struct given to a no-input plant


@pytest.mark.spec("CORE-005")
def test_portfolio_sums_and_broadcasts_steady_plants(wind):
    pf = Portfolio(
        [
            LinearPlant(ConstParams(name="a", kw=2.0)),
            SteadyPlant(ConstParams(name="s", kw=3.0)),
        ]
    )
    out = pf.simulate({"a": wind})
    assert (out["total"] == 13.0).all() and list(out.columns) == ["a", "s", "total"]


@pytest.mark.spec("CORE-005")
def test_portfolio_rejects_bad_setup(wind, idx):
    p = LinearPlant(ConstParams(name="a", kw=1.0))
    with pytest.raises(ValueError):
        Portfolio([p, p])
    with pytest.raises(TypeError):
        Portfolio([p]).simulate({})
    with pytest.raises(ValueError):
        Portfolio([SteadyPlant(ConstParams(name="s", kw=1.0))]).simulate({})
    later = pd.Series(1.0, index=idx + pd.Timedelta("1h"))
    shifted = WindInputs(wind_speed=later, temp_air=later)
    q = LinearPlant(ConstParams(name="q", kw=1.0))
    with pytest.raises(ValueError):
        Portfolio([p, q]).simulate({"a": wind, "q": shifted})
