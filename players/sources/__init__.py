"""Projection sources.

Each module exposes `fetch(season) -> dict[scoring, DataFrame]`, where every
frame carries at least Player / Team / Position / AVG. A source only appears
under the scoring formats it can actually produce.
"""
from players.sources import cbs, espn, sleeper

SOURCES = {
    "cbs": cbs,
    "sleeper": sleeper,
    "espn": espn,
}
