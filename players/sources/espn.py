"""ESPN projections, in the league's own scoring.

ESPN applies the league's configured scoring rules server-side, so its number
needs no conversion — but for the same reason it only exists for the format
the league actually uses. Requires the credentials in `auth`.
"""
from __future__ import annotations

import json

import pandas as pd
import requests

from config import SCORING
from league import import_espn_league as espn_api
from players.names import normalize_team

NAME = "espn"

# ESPN's defaultPositionId -> our position labels.
POSITION_IDS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}
PAGE_SIZE = 400

# ESPN identifies NFL teams by numeric id rather than abbreviation.
PRO_TEAMS = {1: 'ATL', 2: 'BUF', 3: 'CHI', 4: 'CIN', 5: 'CLE', 6: 'DAL', 7: 'DEN', 8: 'DET', 9: 'GB', 10: 'TEN', 11: 'IND', 12: 'KC', 13: 'LV', 14: 'LAR', 15: 'MIA', 16: 'MIN', 17: 'NE', 18: 'NO', 19: 'NYG', 20: 'NYJ', 21: 'PHI', 22: 'ARI', 23: 'PIT', 24: 'LAC', 25: 'SF', 26: 'SEA', 27: 'TB', 28: 'WSH', 29: 'CAR', 30: 'JAX', 33: 'BAL', 34: 'HOU'}


def fetch(season: int) -> dict[str, pd.DataFrame]:
    auth = espn_api.read_auth()
    league_id = auth.get("ESPN_LEAGUE_ID")
    if not (league_id and auth.get("ESPN_S2")):
        raise RuntimeError(
            "ESPN projections need ESPN_LEAGUE_ID and ESPN_S2 in the auth file"
        )

    url = f"{espn_api.BASE}/seasons/{season}/segments/0/leagues/{league_id}"
    filt = {"players": {"limit": PAGE_SIZE,
                        "sortDraftRanks": {"sortPriority": 100, "sortAsc": True,
                                           "value": "PPR"}}}
    resp = requests.get(
        url,
        headers={**espn_api.HEADERS, "x-fantasy-filter": json.dumps(filt)},
        cookies={"espn_s2": auth["ESPN_S2"], "SWID": auth.get("ESPN_SWID", "")},
        params=[("view", "kona_player_info"), ("scoringPeriodId", "0")],
        timeout=45,
    )
    resp.raise_for_status()

    rows = []
    for entry in resp.json().get("players", []):
        player = entry.get("player") or {}
        position = POSITION_IDS.get(player.get("defaultPositionId"))
        if not position:
            continue
        # statSourceId 1 is a projection, statSplitTypeId 0 is full-season.
        total = next(
            (s.get("appliedTotal") for s in player.get("stats", [])
             if s.get("statSourceId") == 1 and s.get("statSplitTypeId") == 0
             and s.get("seasonId") == season),
            None,
        )
        if total is None:
            continue
        rows.append({
            "Player": player.get("fullName", ""),
            "Team": normalize_team(PRO_TEAMS.get(player.get("proTeamId"), "")),
            "Position": position,
            "AVG": total,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return {}
    df = df.sort_values("AVG", ascending=False).reset_index(drop=True)
    # ESPN scores server-side under the league's rules, so this frame is only
    # valid for that one format.
    return {SCORING: df}
