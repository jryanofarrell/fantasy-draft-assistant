"""Value Over Next Available.

VOR asks what a player is worth against a season-long replacement. That is the
right question for valuing a roster and the wrong one for a snake pick, where
the real choice is take-him-now versus wait — and waiting costs you whatever
disappears in between.

VONA compares a player to the best you could plausibly still get at his
position at your *next* pick:

    VONA = his points − points of the best likely survivor at his position

The number of players that vanish comes from the league's own draft history
(see league/draft_history.py), so a league that hoards running backs and never
touches quarterbacks early produces a board shaped like that league.
"""
from __future__ import annotations

import pandas as pd

from league.draft_history import rates_for_round


def pick_to_team(pick: int, teams: int) -> int:
    """Which draft slot owns an overall pick number, snake order."""
    rnd = (pick - 1) // teams + 1
    seat = (pick - 1) % teams + 1
    return seat if rnd % 2 == 1 else teams - seat + 1


def my_picks(slot: int, teams: int, count: int) -> list[int]:
    """The overall pick numbers belonging to one draft slot."""
    picks, pick = [], 1
    while len(picks) < count:
        if pick_to_team(pick, teams) == slot:
            picks.append(pick)
        pick += 1
    return picks


def expected_gone(
    history: dict | None, teams: int, start: int, end: int
) -> dict[str, float]:
    """Expected picks per position strictly between two overall picks.

    Each intervening pick contributes its round's positional shares, so a gap
    spanning a round boundary is weighted by both rounds rather than one.
    """
    totals: dict[str, float] = {}
    for pick in range(start + 1, end):
        rnd = (pick - 1) // teams + 1
        for position, rate in rates_for_round(history, rnd).items():
            totals[position] = totals.get(position, 0.0) + rate
    return totals


def next_available(
    board: pd.DataFrame, position: str, gone: float, points_col: str = "AVG"
) -> tuple[float, str]:
    """Points and name of the best survivor at a position after `gone` picks."""
    pool = board[board["Position"] == position].sort_values(
        points_col, ascending=False
    ).reset_index(drop=True)
    if pool.empty:
        return float("nan"), ""
    index = min(int(round(gone)), len(pool) - 1)
    row = pool.iloc[index]
    return float(row[points_col]), str(row["Player"])


def compute(
    available: pd.DataFrame,
    history: dict | None,
    teams: int,
    current_pick: int,
    next_pick: int | None,
    points_col: str = "AVG",
) -> pd.Series:
    """VONA for every row of `available`.

    With no next pick — the final round — nothing can be lost by waiting, so
    every player scores zero and VOR alone decides.
    """
    if next_pick is None or available.empty:
        return pd.Series(0.0, index=available.index)

    gone = expected_gone(history, teams, current_pick, next_pick)
    baseline = {
        position: next_available(available, position, gone.get(position, 0.0), points_col)[0]
        for position in available["Position"].unique()
    }
    return available.apply(
        lambda r: float(r[points_col]) - baseline.get(r["Position"], float(r[points_col])),
        axis=1,
    )


def summary(
    available: pd.DataFrame,
    history: dict | None,
    teams: int,
    current_pick: int,
    next_pick: int | None,
    points_col: str = "AVG",
) -> pd.DataFrame:
    """Per-position view of what waiting until the next pick would cost."""
    if next_pick is None:
        return pd.DataFrame()
    gone = expected_gone(history, teams, current_pick, next_pick)
    rows = []
    for position in sorted(available["Position"].unique()):
        pool = available[available["Position"] == position].sort_values(
            points_col, ascending=False
        )
        if pool.empty:
            continue
        best = pool.iloc[0]
        expected = gone.get(position, 0.0)
        later_pts, later_name = next_available(available, position, expected, points_col)
        rows.append({
            "Position": position,
            "BestNow": best["Player"],
            "Now": round(float(best[points_col]), 1),
            "ExpGone": round(expected, 1),
            "LikelyAt": later_name,
            "Later": round(later_pts, 1),
            "VONA": round(float(best[points_col]) - later_pts, 1),
        })
    return pd.DataFrame(rows).sort_values("VONA", ascending=False).reset_index(drop=True)
