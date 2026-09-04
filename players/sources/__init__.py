"""Projection sources.

Point-projection sources expose `fetch(season) -> dict[scoring, DataFrame]`,
where every frame carries at least Player / Team / Position / AVG. A source
only appears under the scoring formats it can actually produce.

FantasyPros is kept separate: it publishes rankings rather than projections,
so it enriches the finished board instead of being averaged into it.
"""
from players.sources import cbs, espn, fantasypros, fftoday, manual, sleeper

SOURCES = {
    "cbs": cbs,
    "sleeper": sleeper,
    "fftoday": fftoday,
    "espn": espn,
    "manual": manual,
}

ENRICHERS = {
    "fantasypros": fantasypros,
}
