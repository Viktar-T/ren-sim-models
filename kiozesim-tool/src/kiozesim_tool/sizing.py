"""Sizing a chain from the apps: what it needs, on average, for an output at its end (spec 0019).

Shared by the `size` command (CHAIN-042) and the web page's sizing section (CHAIN-043).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from kiozesim import Chain, Plant, SizingResult
from kiozesim_tool import wiring
from kiozesim_tool.sources import Source


def parse_want(texts: Sequence[str]) -> dict[str, float]:
    """`name=kW` pairs, e.g. `delivered_kw=100`; several may be separated by commas."""
    wanted: dict[str, float] = {}
    for text in (part for t in texts for part in t.split(",") if part.strip()):
        name, sep, value = text.partition("=")
        try:
            if not sep or not name.strip():
                raise ValueError
            wanted[name.strip()] = float(value)
        except ValueError:
            raise ValueError(f"{text.strip()!r}: use name=kW, e.g. delivered_kw=100") from None
    if not wanted:
        raise ValueError("say what is wanted, e.g. delivered_kw=100")
    return wanted


def size(
    plants: Sequence[Plant],  # type: ignore[type-arg]
    sources: Sequence[Source],  # type: ignore[type-arg]
    wires: wiring.Wires,
    plant: str,
    wanted: Mapping[str, float],
) -> SizingResult:
    """Size the chain from its front up to `plant`."""
    names = [p.name for p in plants]
    wiring.check([s.name for s in sources], names, wires, wiring.no_input(plants))
    if plant not in names:
        raise ValueError(f"no plant {plant!r}; plants: {', '.join(names)}")
    by_name = {p.name: p for p in plants}
    return Chain([by_name[n] for n in wiring.chain_to(plant, names, wires)]).size(wanted)


def kw(values: Mapping[str, float]) -> str:
    return ", ".join(f"{k} {v:.2f} kW" for k, v in values.items()) or "nothing"


def feed(values: Mapping[str, float]) -> str:
    return ", ".join(f"{k} {v:.3f} t/day" for k, v in values.items())


def lines(res: SizingResult) -> list[str]:
    """The sizing result as text, back to front."""
    out = []
    for s in res.steps:
        out.append(f"{s.plant}: asked for {kw(s.wanted)}; gives {kw(s.given)}")
        for k, v in s.shortfall.items():
            out.append(f"  short by {k} {v:.2f} kW (at its limit)")
        if s.needs:
            out.append(f"  needs {kw(s.needs)} on average")
        if s.feed_t_per_day:
            out.append(f"  feed {feed(s.feed_t_per_day)}")
    if res.stopped_at is not None:
        out.append(f"stopped at {res.reason}")
    return out
