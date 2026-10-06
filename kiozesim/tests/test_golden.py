import pytest

from .harness import discover, run_case


@pytest.mark.parametrize("case", discover(), ids=lambda c: c.id)
def test_golden(case):
    try:
        run_case(case)
    except NotImplementedError as e:
        pytest.xfail(str(e))
