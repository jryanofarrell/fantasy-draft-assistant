"""FFToday projections.

Published as plain HTML tables in standard scoring, with a reception column,
so every format is one conversion away. Shallower than the other sources at
roughly fifty players a position, which still covers everyone realistically
drafted in a twelve-team league. Also carries bye weeks.
"""
from __future__ import annotations

import io

import pandas as pd
import requests

from config import RECEPTION_POINTS
from players.names import normalize_team

NAME = "fftoday"

URL = ("https://www.fftoday.com/rankings/playerproj.php"
       "?Season={season}&PosID={pos_id}&LeagueID=1")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/537.36"
}
POSITION_IDS = {"QB": 10, "RB": 20, "WR": 30, "TE": 40}

# LeagueID=1 is standard scoring: the published points reconcile exactly from
# the stat line with nothing per reception.
SOURCE_RECEPTION_POINTS = 0.0


def fetch_position(position: str, season: int) -> pd.DataFrame:
    html = requests.get(URL.format(season=season, pos_id=POSITION_IDS[position]),
                        headers=HEADERS, timeout=45).text
    tables = [t for t in pd.read_html(io.StringIO(html)) if t.shape[0] > 10]
    if not tables:
        raise RuntimeError(f"{position}: no projection table found")

    table = max(tables, key=lambda t: t.shape[0])
    # Row 0 groups the columns, row 1 names them, data follows.
    header = [str(c).strip() for c in table.iloc[1]]
    body = table.iloc[2:].copy()
    body.columns = header

    player_col = next(c for c in header if c.startswith("Player"))
    points_col = next(c for c in header if c == "FPts")
    # Rushing and receiving both carry Yds and TD; receptions are unique.
    rec_col = next((c for c in header if c == "Rec"), None)

    out = pd.DataFrame({
        "Player": body[player_col].astype(str).str.strip(),
        "Team": body["Tm"].map(normalize_team) if "Tm" in header else "",
        "Position": position,
        "bye": pd.to_numeric(body["Bye"], errors="coerce") if "Bye" in header else None,
        "standard": pd.to_numeric(body[points_col], errors="coerce"),
        "receptions": (pd.to_numeric(body[rec_col], errors="coerce")
                       if rec_col else 0.0),
    })
    out = out.dropna(subset=["standard"])
    return out[out["Player"] != ""].reset_index(drop=True)


def fetch(season: int) -> dict[str, pd.DataFrame]:
    """One frame per scoring format, converted from standard."""
    frames = [fetch_position(pos, season) for pos in POSITION_IDS]
    raw = pd.concat(frames, ignore_index=True)
    raw["receptions"] = raw["receptions"].fillna(0)

    out = {}
    for fmt, reception_points in RECEPTION_POINTS.items():
        df = raw.copy()
        # Standard already pays nothing per catch, so a format that pays
        # something adds it back rather than taking it away.
        delta = SOURCE_RECEPTION_POINTS - reception_points
        df["AVG"] = df["standard"] - delta * df["receptions"]
        out[fmt] = (df[["Player", "Team", "Position", "AVG", "bye", "receptions"]]
                    .sort_values("AVG", ascending=False).reset_index(drop=True))
    return out
