import pandas as pd
import pytest


@pytest.fixture
def weather() -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=24, freq="h", tz="UTC")
    return pd.DataFrame({"ghi": 100.0, "wind_speed": 5.0, "temp_air": 10.0}, index=idx)
