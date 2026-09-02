import pandas as pd
import numpy as np

from league.config import (
    FLEX_ELIGIBLE,
    LEAGUE_SIZE,
    POSITIONS,
    ROSTER_SLOTS,
    SEASON,
    data_dir,
    position_file,
)

# ===== Load & clean =====
dfs = {}
for pos in POSITIONS:
    fp = position_file(pos, SEASON)
    df = pd.read_csv(fp, na_values=["NaN", "nan", "", " ", "Â", "Â\xa0"], keep_default_na=True)
    df = df.dropna(subset=["Player"]).copy()
    df["Player"] = df["Player"].astype(str).str.strip()
    df["AVG"] = pd.to_numeric(df["AVG"], errors="coerce")
    df = df.dropna(subset=["AVG"]).sort_values("AVG", ascending=False).reset_index(drop=True)
    df["Position"] = pos
    dfs[pos] = df

# ===== Flex-aware replacement lines =====
def compute_replacements(dfs, league_size, roster_slots, flex_eligible):
    # base starters (no flex)
    base_needed = {p: league_size * roster_slots.get(p, 0) for p in dfs.keys()}
    rep_idx = {}
    for p, df in dfs.items():
        want = base_needed.get(p, 0)
        idx = want - 1  # last starter index (0-based)
        if len(df) == 0:
            idx = -1
        else:
            idx = max(-1, min(idx, len(df) - 1))
        rep_idx[p] = idx

    # allocate FLEX slots greedily to the next-best eligible players
    flex_to_fill = league_size * roster_slots.get("FLEX", 0)
    flex_taken = {p: 0 for p in dfs.keys()}
    for _ in range(flex_to_fill):
        candidates = []
        for p in flex_eligible:
            df = dfs.get(p)
            if df is None or df.empty:
                continue
            next_i = rep_idx[p] + 1
            if next_i < len(df):
                candidates.append((p, df.iloc[next_i]["AVG"]))
        if not candidates:
            break
        best_pos, _ = max(candidates, key=lambda t: t[1])
        rep_idx[best_pos] += 1
        flex_taken[best_pos] += 1

    # replacement values (AVG at the last starter for that pos)
    rep_val = {}
    for p, df in dfs.items():
        idx = rep_idx[p]
        rep_val[p] = (df.iloc[idx]["AVG"] if (idx >= 0 and len(df)) else -np.inf)

    return rep_val, rep_idx, flex_taken

rep_val, rep_idx, flex_taken = compute_replacements(dfs, LEAGUE_SIZE, ROSTER_SLOTS, FLEX_ELIGIBLE)

# ===== Compute VOR & rank =====
frames = []
for pos, df in dfs.items():
    out = df.copy()
    out["ReplacementAVG"] = rep_val[pos]
    out["VOR"] = out["AVG"] - out["ReplacementAVG"]
    frames.append(out)

ranked = pd.concat(frames, ignore_index=True)

# Overall board (highest VOR first; tiebreak by higher AVG)
ranked_overall = ranked.sort_values(["VOR", "AVG"], ascending=[False, False]).reset_index(drop=True)
ranked_overall["OverallRank"] = np.arange(1, len(ranked_overall) + 1)

# Per-position ranks (optional)
ranked_overall["PosRank"] = ranked_overall.groupby("Position")["VOR"] \
    .rank(method="first", ascending=False).astype(int)

# Save + show summary
out_path = data_dir(SEASON) / "rankings_vor_flexaware.csv"
ranked_overall.to_csv(out_path, index=False)

print("Replacement lines (after allocating FLEX):")
for p in POSITIONS:
    base = LEAGUE_SIZE * ROSTER_SLOTS.get(p, 0)
    print(f"  {p}: base={base}, +flex={flex_taken.get(p,0)}, "
          f"rep_idx={rep_idx[p]}, replacementAVG={rep_val[p]:.2f}")

print("\nTop 25 overall by VOR:")
print(ranked_overall.loc[:24, ["OverallRank","Player","Position","AVG","ReplacementAVG","VOR","PosRank"]]
      .to_string(index=False))
print(f"\nSaved: {out_path}")
