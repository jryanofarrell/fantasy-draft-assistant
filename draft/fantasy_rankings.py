"""Standalone flex-aware VOR rankings.

Writes the board the draft assistant ranks on to a CSV, for reading away
from the draft.
"""
from config import POINTS_COL, POSITIONS, SCORING, SEASON, scoring_dir
from draft import board as board_mod

ranked_overall, dfs, rep_val, rep_idx, flex_taken = board_mod.build()
ranked_overall.insert(0, "OverallRank", range(1, len(ranked_overall) + 1))
ranked_overall["PosRank"] = (
    ranked_overall.groupby("Position")[POINTS_COL]
    .rank(ascending=False, method="first").astype(int)
)

out_path = scoring_dir(SCORING, SEASON) / "rankings_vor_flexaware.csv"
ranked_overall.to_csv(out_path, index=False)

print("Replacement lines (after allocating FLEX):")
for pos in POSITIONS:
    print(f"  {pos}: +flex={flex_taken.get(pos, 0)}, rep_idx={rep_idx[pos]}, "
          f"replacement={rep_val[pos]:.2f}")

print("\nTop 25 overall by VOR:")
print(ranked_overall.loc[:24, ["OverallRank", "Player", "Position", POINTS_COL,
                               "ReplacementAVG", "VOR", "PosRank"]]
      .to_string(index=False))
print(f"\nSaved: {out_path}")
