"""CBS projections.

CBS publishes full stat lines, which is what lets us derive every scoring
format: only the per-reception term differs between them, so each format is
the PPR projection adjusted by the reception count. Their own `nonppr` pages
disagree with `ppr` by more than receptions, so PPR is treated as the source
of truth and the rest derived from it.
"""
from __future__ import annotations

import io
import re

import pandas as pd
import requests

from config import POSITIONS, RECEPTION_POINTS
from players.names import normalize_team

NAME = "cbs"

# We scrape CBS's PPR pages, which award 1 point per reception.
SOURCE_RECEPTION_POINTS = 1.0

URL_TEMPLATE = (
    "https://www.cbssports.com/fantasy/football/stats/"
    "{pos}/{season}/season/projections/ppr/"
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/537.36"
}

# We scrape CBS's PPR pages, which award 1 point per reception.
SOURCE_RECEPTION_POINTS = 1.0

# CBS renders the player cell as:
#   "J. Gibbs  RB  DET  Jahmyr Gibbs  RB  DET"
# i.e. an abbreviated name then the full name, each followed by pos and team.
PLAYER_CELL = re.compile(r"\s{2,}")


def parse_player_cell(cell: str) -> tuple[str, str, str]:
    """Split a CBS player cell into (full name, position, team)."""
    parts = [p.strip() for p in PLAYER_CELL.split(str(cell).strip()) if p.strip()]
    if len(parts) >= 3:
        # The full name is the third-from-last field; pos and team trail it.
        return parts[-3], parts[-2], parts[-1]
    return str(cell).strip(), "", ""


def flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """CBS uses a two-row header; keep the lower (abbreviated) level."""
    df = df.copy()
    df.columns = [
        c[1].strip() if isinstance(c, tuple) else str(c).strip() for c in df.columns
    ]
    return df


def shorten(col: str) -> str:
    """'yds  Passing Yards' -> 'yds'; disambiguation happens via dedupe()."""
    return PLAYER_CELL.split(col)[0].strip()


def dedupe(names: list[str]) -> list[str]:
    """CBS reuses 'att'/'yds'/'td' for passing and rushing; suffix repeats."""
    seen: dict[str, int] = {}
    out = []
    for n in names:
        if n in seen:
            seen[n] += 1
            out.append(f"{n}.{seen[n]}")
        else:
            seen[n] = 0
            out.append(n)
    return out


def to_league_points(
    points: pd.Series,
    receptions: pd.Series,
    reception_points: float,
    source_reception_points: float = SOURCE_RECEPTION_POINTS,
) -> pd.Series:
    """Restate PPR points under a given per-reception value.

    Only the reception term differs between scoring formats, so rather than
    recomputing fantasy points from the stat line - which would have to
    reproduce CBS's bonuses and rounding exactly - we adjust that one term
    and leave the rest of their projection untouched.
    """
    delta = source_reception_points - reception_points
    return points - delta * receptions.fillna(0)


def fetch_position(pos: str, season: int) -> pd.DataFrame:
    url = URL_TEMPLATE.format(pos=pos, season=season)
    html = requests.get(url, headers=HEADERS, timeout=30).text
    tables = pd.read_html(io.StringIO(html))
    if not tables:
        raise RuntimeError(f"No tables found at {url}")

    df = flatten_columns(tables[0])

    points_col = next((c for c in df.columns if shorten(c) == "fpts"), None)
    if points_col is None:
        raise RuntimeError(
            f"{pos} {season}: no 'fpts' column found — CBS may have changed "
            f"their table layout. Columns: {df.columns.tolist()}"
        )

    parsed = df.iloc[:, 0].apply(parse_player_cell)
    stats = df.iloc[:, 1:]
    stats.columns = dedupe([shorten(c) for c in stats.columns])

    ppr_points = pd.to_numeric(df[points_col], errors="coerce")
    # QB sheets carry no reception column; nothing to convert there.
    receptions = (
        pd.to_numeric(stats["rec"], errors="coerce")
        if "rec" in stats.columns
        else pd.Series(0.0, index=stats.index)
    )

    out = pd.DataFrame(
        {
            "Player": [p[0] for p in parsed],
            "Team": [normalize_team(p[2]) for p in parsed],
            "Position": pos,
            # The draft assistant ranks on AVG. CBS gives a single projection
            # rather than the LOW/AVG/HIGH band the old BeerSheets exports had.
            "PPR": ppr_points,
            "receptions": receptions,
        }
    ).join(stats)

    out = out.dropna(subset=["PPR"])
    out = out[out["Player"].astype(str).str.strip() != ""]
    return out.sort_values("PPR", ascending=False).reset_index(drop=True)




def fetch(season: int) -> dict[str, pd.DataFrame]:
    """One frame per scoring format, derived from the PPR projection."""
    per_position = {pos: fetch_position(pos, season) for pos in POSITIONS}

    out: dict[str, pd.DataFrame] = {}
    for fmt, reception_points in RECEPTION_POINTS.items():
        frames = []
        for pos, df in per_position.items():
            frame = df.copy()
            frame["AVG"] = to_league_points(
                frame["PPR"], frame["receptions"], reception_points
            )
            frames.append(frame)
        merged = pd.concat(frames, ignore_index=True)
        out[fmt] = merged.sort_values("AVG", ascending=False).reset_index(drop=True)
    return out
