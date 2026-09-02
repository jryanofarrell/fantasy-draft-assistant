# draft_assistant.py
import pandas as pd
import numpy as np

from league import draft_history, league
from draft import vona as vona_mod

from config import (
    BENCH_SLOTS,
    LEAGUE,
    FLEX_ELIGIBLE,
    LEAGUE_SIZE,
    MY_SLOT,
    POINTS_COL,
    POSITIONS,
    ROSTER_SLOTS,
    SEASON,
    position_file,
)

# ===== Load & clean =====
dfs = {}
for pos in POSITIONS:
    fp = position_file(pos, SEASON)
    df = pd.read_csv(fp, na_values=["NaN", "nan", "", " ", "Â", "Â\xa0"], keep_default_na=True)
    df = df.dropna(subset=["Player"]).copy()
    df["Player"] = df["Player"].astype(str).str.strip()
    # robust numeric coercion for AVG
    df[POINTS_COL] = (
        df[POINTS_COL].astype(str)
        .str.replace(",", "", regex=False)
        .str.replace(r"[^\d\.\-]", "", regex=True)
        .replace({"": np.nan})
    )
    df[POINTS_COL] = pd.to_numeric(df[POINTS_COL], errors="coerce")
    df = df.dropna(subset=[POINTS_COL]).sort_values(POINTS_COL, ascending=False).reset_index(drop=True)
    df["Position"] = pos
    dfs[pos] = df

def compute_replacements(dfs, league_size, roster_slots, flex_eligible):
    # base starters (no flex)
    base_needed = {p: league_size * roster_slots.get(p, 0) for p in dfs.keys()}
    rep_idx = {}
    for p, d in dfs.items():
        want = base_needed.get(p, 0)
        idx = want - 1
        if len(d) == 0:
            idx = -1
        else:
            idx = max(-1, min(idx, len(d) - 1))
        rep_idx[p] = idx

    # allocate FLEX slots greedily to next-best eligible players
    flex_to_fill = league_size * roster_slots.get("FLEX", 0)
    flex_taken = {p: 0 for p in dfs.keys()}
    for _ in range(flex_to_fill):
        candidates = []
        for p in flex_eligible:
            d = dfs.get(p)
            if d is None or d.empty:
                continue
            next_i = rep_idx[p] + 1
            if next_i < len(d):
                candidates.append((p, d.iloc[next_i][POINTS_COL]))
        if not candidates:
            break
        best_pos, _ = max(candidates, key=lambda t: t[1])
        rep_idx[best_pos] += 1
        flex_taken[best_pos] += 1

    rep_val = {}
    for p, d in dfs.items():
        idx = rep_idx[p]
        val = float(d.iloc[idx][POINTS_COL]) if (idx >= 0 and len(d)) else -np.inf
        rep_val[p] = val
    return rep_val, rep_idx, flex_taken

rep_val, rep_idx, flex_taken = compute_replacements(dfs, LEAGUE_SIZE, ROSTER_SLOTS, FLEX_ELIGIBLE)

# Positional tendencies from this league's own past drafts, used for VONA.
HISTORY = draft_history.load()

# ===== Build VOR pool =====
frames = []
for pos, d in dfs.items():
    out = d.copy()
    out["ReplacementAVG"] = rep_val[pos]
    out["VOR"] = out[POINTS_COL] - out["ReplacementAVG"]
    frames.append(out)

ranked_overall = pd.concat(frames, ignore_index=True)
for col in [POINTS_COL, "VOR", "ReplacementAVG"]:
    ranked_overall[col] = pd.to_numeric(ranked_overall[col], errors="coerce")

ranked_overall = ranked_overall.sort_values(["VOR", POINTS_COL], ascending=[False, False]).reset_index(drop=True)
ranked_overall["Key"] = (ranked_overall["Player"].str.strip() + " (" + ranked_overall["Position"] + ")").str.lower()

# ===== Replacement "ghost" lineup (baseline for marginal gain) =====
def build_replacement_skeleton(rep_val: dict, pool_cols: list[str]) -> pd.DataFrame:
    rows = []

    def add(pos: str, k: int, prefix: str):
        rv = rep_val.get(pos, -np.inf)
        rv = float(rv) if np.isfinite(rv) else 0.0  # if somehow -inf, treat as 0
        for i in range(k):
            rows.append({
                "Player": f"{prefix}-{pos}-{i+1}",
                "Position": pos,
                POINTS_COL: rv,
                "VOR": 0.0,
                "ReplacementAVG": rv,
                "Key": f"{prefix.lower()}-{pos}-{i+1}"
            })

    # base starters
    add("QB", ROSTER_SLOTS.get("QB", 0), "REPL")
    add("RB", ROSTER_SLOTS.get("RB", 0), "REPL")
    add("WR", ROSTER_SLOTS.get("WR", 0), "REPL")
    add("TE", ROSTER_SLOTS.get("TE", 0), "REPL")

    # For FLEX: create 2 ghosts PER eligible position; lineup chooser will take the best two
    for p in FLEX_ELIGIBLE:
        add(p, ROSTER_SLOTS.get("FLEX", 0), "REPL-FLEX")

    skel = pd.DataFrame(rows)
    # Align columns with the pool (any missing columns will be NaN)
    return skel.reindex(columns=pool_cols, fill_value=np.nan)

skeleton = build_replacement_skeleton(rep_val, list(ranked_overall.columns))

# ===== Helpers =====
try:
    from prompt_toolkit import prompt
    from prompt_toolkit.completion import WordCompleter, FuzzyCompleter
    HAVE_PT = True
except Exception:
    HAVE_PT = False

def remaining_display(df):
    return (df["Player"] + " (" + df["Position"] + ")").tolist()

def pick_to_team(pick: int, teams: int) -> int:
    rnd = (pick - 1) // teams + 1
    pos = (pick - 1) % teams + 1
    return pos if rnd % 2 == 1 else teams - pos + 1

def best_starting_lineup_indices(roster_df: pd.DataFrame):
    work = roster_df.copy()
    work[POINTS_COL] = pd.to_numeric(work[POINTS_COL], errors="coerce")
    work = work.dropna(subset=[POINTS_COL])

    chosen = set()

    def pick_top_indices(df, pos, k):
        if k <= 0:
            return []
        sub = df[df["Position"] == pos]
        if sub.empty:
            return []
        return sub.nlargest(k, POINTS_COL).index.tolist()

    # Fill core slots
    for pos, k in [("QB", 1), ("RB", 2), ("WR", 2), ("TE", 1)]:
        idxs = pick_top_indices(work.drop(index=list(chosen), errors="ignore"), pos, k)
        chosen.update(idxs)

    # Fill FLEX from remaining RB/WR/TE
    remaining = work.drop(index=list(chosen), errors="ignore")
    flex_pool = remaining[remaining["Position"].isin(FLEX_ELIGIBLE)]
    if not flex_pool.empty:
        chosen.update(flex_pool.nlargest(ROSTER_SLOTS["FLEX"], POINTS_COL).index.tolist())

    return chosen

def best_starting_lineup_points(roster_df: pd.DataFrame) -> float:
    if roster_df.empty:
        return 0.0
    idxs = best_starting_lineup_indices(roster_df)
    return float(roster_df.loc[list(idxs), POINTS_COL].sum()) if idxs else 0.0

def marginal_gain(my_roster: pd.DataFrame, candidate_row: pd.Series) -> float:
    before = best_starting_lineup_points(pd.concat([skeleton, my_roster], ignore_index=True))
    after = best_starting_lineup_points(pd.concat([skeleton, my_roster, candidate_row.to_frame().T], ignore_index=True))
    return float(after - before)

def suggest_top_by_positions(available: pd.DataFrame, my_roster: pd.DataFrame,
                             positions: set[str], k: int = 10) -> pd.DataFrame:
    cand = available[available["Position"].isin(positions)].copy()
    # keep calculations safe
    for col in [POINTS_COL, "VOR"]:
        cand[col] = pd.to_numeric(cand[col], errors="coerce")
    cand = cand.dropna(subset=[POINTS_COL, "VOR"])

    # prefilter for speed
    pre = cand.nlargest(min(len(cand), 120), ["VOR", POINTS_COL]).copy()

    gains = []
    for _, r in pre.iterrows():
        gains.append(marginal_gain(my_roster, r))
    pre["MarginalGain"] = gains

    pre = pre.sort_values(["MarginalGain", "VOR", POINTS_COL],
                          ascending=[False, False, False])
    return pre.head(k)[["Player", "Position", POINTS_COL, "VOR", "MarginalGain", "Key"]].reset_index(drop=True)


def suggest_top(available: pd.DataFrame, my_roster: pd.DataFrame, k: int = 10,
                current_pick: int | None = None,
                next_pick: int | None = None) -> pd.DataFrame:
    cand = available.copy()
    # keep calculations safe
    for col in [POINTS_COL, "VOR"]:
        cand[col] = pd.to_numeric(cand[col], errors="coerce")
    cand = cand.dropna(subset=[POINTS_COL, "VOR"])

    # prefilter for speed
    pre = cand.nlargest(min(len(cand), 120), ["VOR", POINTS_COL]).copy()

    gains = []
    for _, r in pre.iterrows():
        gains.append(marginal_gain(my_roster, r))
    pre["MarginalGain"] = gains
    if current_pick is not None:
        pre["VONA"] = vona_mod.compute(
            pre, HISTORY, LEAGUE_SIZE, current_pick, next_pick, POINTS_COL
        )
    else:
        pre["VONA"] = 0.0

    # VONA orders the board, but marginal gain still breaks ties: a player
    # who cannot crack your starting lineup is worth less than his scarcity
    # suggests.
    pre = pre.sort_values(["VONA", "MarginalGain", "VOR"], ascending=False)
    return pre.head(k)[["Player", "Position", POINTS_COL, "VOR", "MarginalGain",
                        "VONA", "Key"]].reset_index(drop=True)

def pretty_roster_summary(my_roster: pd.DataFrame):
    if my_roster.empty:
        return "Starters: 0/8 | Bench: 0/5"
    starters_idx = best_starting_lineup_indices(my_roster)
    starters = my_roster.loc[list(starters_idx)]
    bench = my_roster.drop(index=list(starters_idx), errors="ignore")
    return (f"Starters: {len(starters)}/8 | Bench: {len(bench)}/{BENCH_SLOTS} | "
            f"Starter Pts: {starters[POINTS_COL].sum():.1f}")

# ===== Interactive loop =====
def main():
    available = ranked_overall.copy()
    my_roster = ranked_overall.iloc[0:0].copy()  # empty with same columns

    print(f"\n=== Draft Assistant (Greedy + Flex-aware + Bench={BENCH_SLOTS}) ===")
    print(f"Autocomplete: {'ON' if HAVE_PT else 'OFF'}")
    print("Commands: 'auto' for other teams to auto-pick top VOR, 'quit' to exit.\n")

    # Print replacement lines once
    print("Replacement lines (after FLEX allocation):")
    for p in POSITIONS:
        base = LEAGUE_SIZE * ROSTER_SLOTS.get(p, 0)
        print(f"  {p}: base={base}, replacementAVG={rep_val[p]:.2f}")
    print()

    print(league.summary(LEAGUE))
    if HISTORY:
        print(f"  Draft history: {len(HISTORY.get('seasons', []))} seasons "
              f"({HISTORY.get('picks', 0)} picks) informing VONA")
    else:
        print("  Draft history unavailable — VONA disabled, VOR only")
    print()

    my_schedule = vona_mod.my_picks(MY_SLOT, LEAGUE_SIZE, LEAGUE.drafted_roster_size + 4)

    pick = 1
    total_my_picks_allowed = LEAGUE.drafted_roster_size

    if HAVE_PT:
        base_completer = WordCompleter(remaining_display(available))
        completer = FuzzyCompleter(base_completer)
    else:
        base_completer = None
        completer = None

    while True:
        if available.empty:
            print("No players left. Draft over.")
            break

        if len(my_roster) >= total_my_picks_allowed:
            starters = sum(ROSTER_SLOTS.values())
            print(
                f"\n✅ You filled {total_my_picks_allowed} roster spots "
                f"({starters} starters + {BENCH_SLOTS} bench). Draft assistant done."
            )
            break

        team = pick_to_team(pick, LEAGUE_SIZE)
        me = (team == MY_SLOT)

        print(f"\n--- Pick #{pick} --- ")

        upcoming = [p for p in my_schedule if p >= pick]
        current_target = upcoming[0] if upcoming else None
        following = upcoming[1] if len(upcoming) > 1 else None
        sugg = suggest_top(available, my_roster, k=10,
                           current_pick=current_target, next_pick=following)
        if sugg.empty:
            print("No candidates to suggest.")
            break

        view = sugg[["Player", "Position", POINTS_COL, "VOR", "MarginalGain",
                     "VONA"]].rename(columns={POINTS_COL: "AVG"})
        print(view.to_string(index=True))

        if me and current_target and following:
            gap = following - current_target - 1
            print(f"\nWaiting until pick {following} costs you ({gap} picks away):")
            print(vona_mod.summary(available, HISTORY, LEAGUE_SIZE,
                                   current_target, following, POINTS_COL).to_string(index=False))

        rbwr = suggest_top_by_positions(available, my_roster, {"RB", "WR"}, k=10)
        if not rbwr.empty:
            print("\nTop RB/WR:")
            print(rbwr[["Player", "Position", POINTS_COL, "VOR", "MarginalGain"]]
                .rename(columns={POINTS_COL: "AVG"})
                .to_string(index=True)
            )


        if me:
            print(f"\n[{pretty_roster_summary(my_roster)}]")

            default_choice = f"{sugg.iloc[0]['Player']} ({sugg.iloc[0]['Position']})"
            if HAVE_PT:
                user_in = prompt(f"Your pick (default: {default_choice}): ", completer=completer).strip()
            else:
                user_in = input(f"Your pick (default: {default_choice}): ").strip()

            if user_in.lower() in {"quit", "exit"}:
                print("Exiting. Good luck!")
                break
            if user_in == "":
                user_in = default_choice

            key = user_in.strip().lower()
            mask = available["Key"] == key
            if not mask.any():
                print("Name not found. Use exact 'Name (POS)'.")
                continue

            row = available.loc[mask].iloc[0]
            my_roster = pd.concat([my_roster, row.to_frame().T], ignore_index=True)
            available = available.loc[~mask].reset_index(drop=True)

            if HAVE_PT:
                base_completer.words = remaining_display(available)

            print(f"✅ You drafted: {row['Player']} ({row['Position']}) — AVG {row[POINTS_COL]:.2f}, VOR {row['VOR']:.2f}")
            pick += 1

        else:
            # Other team picks; either type a name or 'auto' (top VOR)
            top_row = available.nlargest(1, ["VOR", POINTS_COL]).iloc[0]
            default_other = f"{top_row['Player']} ({top_row['Position']})"
            if HAVE_PT:
                user_in = prompt(f"(Team {team}) took (or 'auto', default {default_other}): ",
                                 completer=base_completer).strip()
            else:
                user_in = input(f"(Team {team}) took (or 'auto', default {default_other}): ").strip()

            if user_in.lower() in {"quit", "exit"}:
                print("Exiting.")
                break
            if user_in == "" or user_in.lower() == "auto":
                key = default_other.lower()
            else:
                key = user_in.strip().lower()

            mask = available["Key"] == key
            if not mask.any():
                print("Name not found. Try exact 'Name (POS)' or 'auto'.")
                continue

            row = available.loc[mask].iloc[0]
            available = available.loc[~mask].reset_index(drop=True)
            if HAVE_PT:
                base_completer.words = remaining_display(available)

            print(f"Team {team} drafted: {row['Player']} ({row['Position']})")
            pick += 1

    # Final roster summary
    if len(my_roster):
        starters_idx = best_starting_lineup_indices(my_roster)
        starters = my_roster.loc[list(starters_idx)]
        bench = my_roster.drop(index=list(starters_idx), errors="ignore")
        print("\n=== Your Starters ===")
        print(starters.sort_values(["Position", POINTS_COL], ascending=[True, False])
                    [["Player", "Position", POINTS_COL, "VOR"]]
                    .rename(columns={POINTS_COL: "AVG"}).to_string(index=False))
        if not bench.empty:
            print("\n--- Bench ---")
            print(bench.sort_values(["VOR", POINTS_COL], ascending=[False, False])
                      [["Player", "Position", POINTS_COL, "VOR"]]
                      .rename(columns={POINTS_COL: "AVG"}).to_string(index=False))

if __name__ == "__main__":
    main()
