"""Projections pasted in by hand.

Some sources have no API worth scraping — BeerSheets is generated per league
from a form and publishes nothing machine-readable, and FantasyPros gates its
projections. Rather than scrape fragile pages, drop a CSV into

    data/<season>/<scoring>/sources/manual/<POS>-Table 1.csv

and it joins the consensus like any other source. Only a player name, a
position and a points column are required; the column may be called AVG,
FPTS, PTS, POINTS or PROJ, in any capitalisation.
"""
from __future__ import annotations

import pandas as pd

from config import POSITIONS, SCORING_FORMATS, position_file

NAME = "manual"

POINTS_ALIASES = ["avg", "fpts", "pts", "points", "proj", "projection", "fantasy points"]
NAME_ALIASES = ["player", "name", "player name"]
POSITION_ALIASES = ["position", "pos"]
TEAM_ALIASES = ["team", "tm"]


def _pick(columns: list[str], aliases: list[str]) -> str | None:
    lowered = {str(c).strip().lower(): c for c in columns}
    for alias in aliases:
        if alias in lowered:
            return lowered[alias]
    return None


def _read(path, position: str) -> pd.DataFrame | None:
    df = pd.read_csv(path)
    if df.empty:
        return None

    name_col = _pick(list(df.columns), NAME_ALIASES)
    points_col = _pick(list(df.columns), POINTS_ALIASES)
    if not name_col or not points_col:
        raise ValueError(
            f"{path.name}: need a player-name column ({'/'.join(NAME_ALIASES)}) "
            f"and a points column ({'/'.join(POINTS_ALIASES)}); "
            f"found {list(df.columns)[:8]}"
        )

    pos_col = _pick(list(df.columns), POSITION_ALIASES)
    team_col = _pick(list(df.columns), TEAM_ALIASES)

    out = pd.DataFrame({
        "Player": df[name_col].astype(str).str.strip(),
        "Team": df[team_col].astype(str).str.strip() if team_col else "",
        # Fall back to the filename's position when the sheet omits one.
        "Position": df[pos_col].astype(str).str.strip().str.upper()
                    if pos_col else position,
        "AVG": pd.to_numeric(df[points_col], errors="coerce"),
    })
    out = out[out["Player"] != ""].dropna(subset=["AVG"])
    return out if not out.empty else None


def fetch(season: int) -> dict[str, pd.DataFrame]:
    """Read whatever has been dropped in, for any scoring format."""
    out: dict[str, pd.DataFrame] = {}
    for scoring in SCORING_FORMATS:
        frames = []
        for pos in POSITIONS:
            path = position_file(pos, season, scoring, source=NAME)
            if not path.exists():
                continue
            frame = _read(path, pos)
            if frame is not None:
                frames.append(frame)
        if frames:
            merged = pd.concat(frames, ignore_index=True)
            out[scoring] = merged.sort_values("AVG", ascending=False).reset_index(drop=True)
    return out
