"""Charts drawn on the server as inline SVG: power (UI-015) and every other output (spec 0020)."""

from __future__ import annotations

import io

import matplotlib
import pandas as pd
from matplotlib.figure import Figure


def _svg(table: pd.DataFrame, ylabel: str, title: str = "") -> str:
    """One line per column over UTC time; a `total` column is drawn bold. Returns the `<svg>`."""
    fig = Figure(figsize=(9, 3.5), layout="constrained")
    ax = fig.add_subplot()
    for col in table.columns:
        style = {"color": "black", "linewidth": 2} if col == "total" else {"linewidth": 1}
        ax.plot(table.index, table[col], label=str(col), **style)
    if title:
        ax.set_title(title)
    ax.set_xlabel("time (UTC)")
    ax.set_ylabel(ylabel)
    ax.grid(True, color="#d0d0d0")
    ax.legend(loc="upper left", frameon=False)
    buf = io.StringIO()
    # text stays text (not paths), so plant names in the legend are real text
    with matplotlib.rc_context({"svg.fonttype": "none", "svg.hashsalt": "kiozesim"}):
        fig.savefig(buf, format="svg", metadata={"Date": None})
    svg = buf.getvalue()
    return svg[svg.index("<svg") :]


def power_svg(power_kw: pd.DataFrame) -> str:
    """One line per column (plants and `total`), kW over UTC time (UI-015)."""
    return _svg(power_kw, "power_kw")


def output_fields(outputs: dict[str, pd.DataFrame]) -> list[str]:
    """Every output field except power_kw, in the order fields first appear (PLOT-002).

    `outputs` is per plant, in the order of the plant boxes.
    """
    fields: list[str] = []
    for table in outputs.values():
        for column in table.columns:
            name = str(column)
            if name != "power_kw" and name not in fields:
                fields.append(name)
    return fields


def output_svgs(outputs: dict[str, pd.DataFrame]) -> list[tuple[str, str]]:
    """(field, `<svg>`) per output field: one chart per field, one line per plant (PLOT-001)."""
    charts: list[tuple[str, str]] = []
    for field in output_fields(outputs):
        lines = pd.DataFrame(
            {plant: table[field] for plant, table in outputs.items() if field in table.columns}
        )
        charts.append((field, _svg(lines, field, title=field)))
    return charts
