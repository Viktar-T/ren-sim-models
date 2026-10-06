"""Power chart drawn on the server as an inline SVG (UI-015)."""

from __future__ import annotations

import io

import matplotlib
import pandas as pd
from matplotlib.figure import Figure


def power_svg(power_kw: pd.DataFrame) -> str:
    """One line per column (plants and `total`), kW over UTC time. Returns the `<svg>` element."""
    fig = Figure(figsize=(9, 3.5), layout="constrained")
    ax = fig.add_subplot()
    for col in power_kw.columns:
        style = {"color": "black", "linewidth": 2} if col == "total" else {"linewidth": 1}
        ax.plot(power_kw.index, power_kw[col], label=str(col), **style)
    ax.set_xlabel("time (UTC)")
    ax.set_ylabel("power_kw")
    ax.grid(True, color="#d0d0d0")
    ax.legend(loc="upper left", frameon=False)
    buf = io.StringIO()
    # text stays text (not paths), so plant names in the legend are real text
    with matplotlib.rc_context({"svg.fonttype": "none", "svg.hashsalt": "kiozesim"}):
        fig.savefig(buf, format="svg", metadata={"Date": None})
    svg = buf.getvalue()
    return svg[svg.index("<svg") :]
