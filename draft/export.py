"""Write the whole board to one CSV, ranked.

The draft tools show a top ten. This is the same board in full — every
player, every metric, in rank order — for reading away from the draft or
sorting in a spreadsheet.

    ./run.py export
    ./run.py export --scoring ppr --out ~/board.csv

VONA depends on which pick you are measuring from, so it is computed for
each of your picks in turn and written as one column per pick: what waiting
from that pick to your next one would cost, for every player.
"""
from __future__ import annotations

import argparse

import pandas as pd

from config import (
    LEAGUE,
    LEAGUE_SIZE,
    MY_SLOT,
    POINTS_COL,
    SCORING,
    SCORING_FORMATS,
    SEASON,
    scoring_dir,
)
from draft import board as board_mod
from draft import vona as vona_mod
from league.draft_history import load as load_history


def build(scoring: str, season: int) -> pd.DataFrame:
    board, _, replacement, _, _ = board_mod.build(season, scoring)
    history = load_history()
    schedule = vona_mod.my_picks(MY_SLOT, LEAGUE_SIZE,
                                 LEAGUE.drafted_roster_size + 4)

    out = board.copy()
    out.insert(0, "OverallRank", range(1, len(out) + 1))
    out["PosRank"] = (out.groupby("Position")[POINTS_COL]
                      .rank(ascending=False, method="first").astype(int))

    for i, pick in enumerate(schedule[:-1]):
        following = schedule[i + 1]
        out[f"VONA_p{pick}"] = vona_mod.compute(
            out, history, LEAGUE_SIZE, pick, following, POINTS_COL, pool=out
        ).round(2)

    lead = ["OverallRank", "Player", "Position", "PosRank", "Team", POINTS_COL,
            "ReplacementAVG", "VOR"]
    rest = [c for c in out.columns if c not in lead and c != "Key"]
    return out[lead + rest]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scoring", default=SCORING, choices=SCORING_FORMATS)
    ap.add_argument("--season", type=int, default=SEASON)
    ap.add_argument("--out", help="destination csv (default: alongside the data)")
    args = ap.parse_args()

    table = build(args.scoring, args.season)
    path = (args.out if args.out
            else scoring_dir(args.scoring, args.season) / "board-full.csv")
    table.to_csv(path, index=False)

    vona_cols = [c for c in table.columns if c.startswith("VONA_p")]
    print(f"{len(table)} players -> {path}")
    print(f"  columns: {len(table.columns)}  "
          f"(VONA for {len(vona_cols)} of your picks: "
          f"{', '.join(c.replace('VONA_p', '#') for c in vona_cols[:6])}...)")
    print()
    show = ["OverallRank", "Player", "Position", POINTS_COL, "VOR"] + vona_cols[:3]
    print(table.head(15)[show].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
