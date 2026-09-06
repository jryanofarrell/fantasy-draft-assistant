"""Sleeper projections.

Free, unauthenticated, and the only source that publishes all three scoring
formats natively rather than derived. Also far deeper than the others.
"""
from __future__ import annotations

import pandas as pd
import requests

from config import POSITIONS
from players.names import normalize_team

NAME = "sleeper"
URL = "https://api.sleeper.app/projections/nfl/{season}"
# Sleeper's own field names for each scoring format.
POINTS_FIELD = {"standard": "pts_std", "half_ppr": "pts_half_ppr", "ppr": "pts_ppr"}


def fetch(season: int) -> dict[str, pd.DataFrame]:
    rows = []
    for pos in POSITIONS:
        resp = requests.get(
            URL.format(season=season),
            params={"season_type": "regular", "position[]": pos,
                    "order_by": "pts_half_ppr"},
            timeout=45,
        )
        resp.raise_for_status()
        for entry in resp.json():
            player = entry.get("player") or {}
            stats = entry.get("stats") or {}
            name = f"{player.get('first_name','')} {player.get('last_name','')}".strip()
            if not name:
                continue
            rows.append({
                "Player": name,
                "Team": normalize_team(entry.get("team") or player.get("team")),
                "Position": pos,
                "injury_status": player.get("injury_status") or "",
                **{fmt: stats.get(field) for fmt, field in POINTS_FIELD.items()},
            })

    raw = pd.DataFrame(rows)
    out = {}
    for fmt in POINTS_FIELD:
        df = raw[["Player", "Team", "Position", "injury_status", fmt]].copy()
        df = df.rename(columns={fmt: "AVG"})
        df["AVG"] = pd.to_numeric(df["AVG"], errors="coerce")
        df = df.dropna(subset=["AVG"])
        out[fmt] = df.sort_values("AVG", ascending=False).reset_index(drop=True)
    return out
