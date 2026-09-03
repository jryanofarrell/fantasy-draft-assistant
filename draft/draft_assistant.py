# draft_assistant.py
import argparse
import time

import pandas as pd
import numpy as np

from league import draft_history, league
from draft import board as board_mod
from draft import live as live_mod
from draft import table as table_mod
from draft import vona as vona_mod
from players.names import normalize_name

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

# ===== Board =====
ranked_overall, dfs, rep_val, rep_idx, flex_taken = board_mod.build()

# Positional tendencies from this league's own past drafts, used for VONA.
HISTORY = draft_history.load()

# Starting slots the assistant actually drafts for (K and D/ST excluded).
DRAFTED_STARTERS = sum(ROSTER_SLOTS.values())

# Candidates scored for marginal gain before taking the top k. Marginal gain
# reorders players but never lifts one past dozens of higher-VOR peers, so a
# deep pool costs time without changing the board.
CANDIDATE_POOL = 50

# Seconds of an in-progress draft with no picks before saying something. ESPN
# flags a draft in progress as soon as its room opens, so this has to outlast
# the pre-draft countdown to avoid crying wolf.
SILENT_WARN_AFTER = 120

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

    # Core slots come from league.yaml like everything else; a literal here
    # would silently mis-score marginal gain the moment the roster changes.
    for pos, k in [(p, ROSTER_SLOTS.get(p, 0)) for p in POSITIONS]:
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

def marginal_gain(my_roster: pd.DataFrame, candidate_row: pd.Series,
                  before: float | None = None) -> float:
    """How much a candidate improves your best legal starting lineup.

    `before` is the lineup without him, which is the same for every candidate
    on a given roster — pass it in when scoring a batch rather than paying for
    it once per player.
    """
    if before is None:
        before = best_starting_lineup_points(
            pd.concat([skeleton, my_roster], ignore_index=True))
    after = best_starting_lineup_points(
        pd.concat([skeleton, my_roster, candidate_row.to_frame().T], ignore_index=True))
    return float(after - before)


def score_candidates(pre: pd.DataFrame, my_roster: pd.DataFrame) -> list[float]:
    """Marginal gain for a batch of candidates, baseline computed once."""
    before = best_starting_lineup_points(
        pd.concat([skeleton, my_roster], ignore_index=True))
    return [marginal_gain(my_roster, r, before) for _, r in pre.iterrows()]

def suggest_top(available: pd.DataFrame, my_roster: pd.DataFrame, k: int = 10,
                current_pick: int | None = None,
                next_pick: int | None = None,
                pool: pd.DataFrame | None = None) -> pd.DataFrame:
    cand = available.copy()
    # keep calculations safe
    for col in [POINTS_COL, "VOR"]:
        cand[col] = pd.to_numeric(cand[col], errors="coerce")
    cand = cand.dropna(subset=[POINTS_COL, "VOR"])

    # prefilter for speed
    pre = cand.nlargest(min(len(cand), CANDIDATE_POOL), ["VOR", POINTS_COL]).copy()
    pre["MarginalGain"] = score_candidates(pre, my_roster)
    if current_pick is not None:
        pre["VONA"] = vona_mod.compute(
            pre, HISTORY, LEAGUE_SIZE, current_pick, next_pick, POINTS_COL,
            pool=pool if pool is not None else cand,
        )
    else:
        pre["VONA"] = 0.0

    # Marginal gain leads, because a player who improves your starting lineup
    # is worth more than one who only improves the bench. But it measures the
    # starting lineup *only*, so once your slots are full it goes flat — and
    # arrives as floating-point dust rather than a clean zero, which meant
    # near-ties never actually tied and the order fell through to raw value.
    # Rounding collapses that dust so VONA breaks the tie, which is precisely
    # the phase where positional scarcity is the whole decision.
    pre["MarginalGain"] = pre["MarginalGain"].round(2) + 0.0
    pre = pre.sort_values(["MarginalGain", "VONA", "VOR"], ascending=False)
    return pre.head(k)[["Player", "Position", POINTS_COL, "VOR", "MarginalGain",
                        "VONA", "Key"]].reset_index(drop=True)

def resolve_typed(board: pd.DataFrame, text: str):
    """Find who someone meant from whatever they typed.

    Manual entry used to demand the exact "Name (POS)" the board prints,
    which is a lot of keystrokes per pick with a clock running. This accepts
    a bare surname, a partial name, or the full string, and only asks for
    more when the text genuinely fits several players.

    Returns (row, candidates). A row means one match; otherwise candidates
    holds what it narrowed to.
    """
    typed = normalize_name(text)
    if not typed:
        return None, []

    names = board["Player"].map(normalize_name)
    for match in (names == typed,
                  names.str.startswith(typed),
                  names.str.contains(typed, regex=False)):
        hits = board[match]
        if len(hits) == 1:
            return hits.iloc[0], []
        if len(hits) > 1:
            # Several plausible; prefer the best available among them.
            return None, hits.nlargest(min(len(hits), 6), "VOR")
    return None, []


def find_in_board(board: pd.DataFrame, name: str, position: str):
    """Locate a drafted player on our board.

    Live feeds spell names their own way, so match on the same normalised
    form the projection sources are merged with rather than raw text.
    """
    if board.empty:
        return None
    target = normalize_name(name)
    hits = board[
        board["Player"].map(normalize_name).eq(target)
        & board["Position"].str.upper().eq(str(position).upper())
    ]
    if hits.empty:
        hits = board[board["Player"].map(normalize_name).eq(target)]
    return hits.index[0] if len(hits) else None


def pretty_roster_summary(my_roster: pd.DataFrame):
    if my_roster.empty:
        return f"Starters: 0/{DRAFTED_STARTERS} | Bench: 0/{BENCH_SLOTS}"
    starters_idx = best_starting_lineup_indices(my_roster)
    starters = my_roster.loc[list(starters_idx)]
    bench = my_roster.drop(index=list(starters_idx), errors="ignore")
    return (f"Starters: {len(starters)}/{DRAFTED_STARTERS} | Bench: {len(bench)}/{BENCH_SLOTS} | "
            f"Starter Pts: {starters[POINTS_COL].sum():.1f}")

# ===== Interactive loop =====
def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Interactive snake-draft assistant")
    ap.add_argument("--live", action="store_true",
                    help="follow a real draft instead of typing every pick")
    ap.add_argument("--provider", choices=["espn", "sleeper", "local"],
                    default="espn")
    ap.add_argument("--league-id", help="ESPN league or mock-lobby id")
    ap.add_argument("--draft-id", help="Sleeper draft id")
    ap.add_argument("--interval", type=float, default=5.0,
                    help="seconds between polls in live mode")
    ap.add_argument("--season", type=int, default=SEASON,
                    help="season to follow; useful for replaying a past draft")
    return ap.parse_args(argv)


def window_for(my_next: int, schedule: list[int]) -> tuple[int, int]:
    """The stretch of picks VONA prices: your pick to your next one.

    Always your own window, whoever is currently on the clock. The question
    is what a player costs *you* by being passed over — the gap between
    taking him at your turn and taking whoever is left at the turn after.
    Watching someone else pick doesn't change that, it just updates the board
    the answer is read off.
    """
    following = next((p for p in schedule if p > my_next), None)
    return my_next, following


def apply_pick(available, my_roster, entry, mine: bool):
    """Remove a drafted player from the board, adding him to your roster.

    Returns the updated frames and the matched row, or None when the player
    isn't on our board at all — kickers and defenses have no projections, and
    a very deep pick may be outside every source.
    """
    idx = find_in_board(available, entry["player"], entry["position"])
    if idx is None:
        return available, my_roster, None
    row = available.loc[idx]
    if mine:
        my_roster = pd.concat([my_roster, row.to_frame().T], ignore_index=True)
    return available.drop(index=idx).reset_index(drop=True), my_roster, row


def run_live(args):
    """Watch a draft: advise on your picks, absorb everyone else's."""
    available = ranked_overall.copy()
    my_roster = ranked_overall.iloc[0:0].copy()

    draft = live_mod.connect(args.provider, args.league_id, args.draft_id, args.season)
    if isinstance(draft, live_mod.EspnDraft):
        draft.prefetch()

    print(f"\n=== Live draft — {args.provider} ===")
    print(league.summary(LEAGUE))
    if HISTORY:
        print(f"  Draft history: {len(HISTORY.get('seasons', []))} seasons "
              f"informing VONA")
    my_schedule = vona_mod.my_picks(MY_SLOT, LEAGUE_SIZE,
                                    LEAGUE.drafted_roster_size + 4)

    # Ownership beats slot arithmetic: draft order is reshuffled every season,
    # so a configured slot can silently mislabel picks in another season.
    my_team_id = None
    if isinstance(draft, live_mod.EspnDraft):
        try:
            my_team_id = draft.my_team_id()
        except Exception:
            my_team_id = None
    state0 = draft.state()
    on_the_clock = {
        p.get("overallPickNumber") or p.get("pick_no"):
            state0["teams"].get(p.get("teamId") or p.get("roster_id"), "")
        for p in state0["picks"]
    }
    if my_team_id is not None:
        name = state0["teams"].get(my_team_id, f"team {my_team_id}")
        print(f"  You are: {name} (team {my_team_id})")
        owned = [p.get("overallPickNumber") for p in state0["picks"]
                 if p.get("teamId") == my_team_id]
        owned = sorted(x for x in owned if x)
        if owned:
            if owned[:len(my_schedule)] != my_schedule[:len(owned)]:
                print(f"  ! league.yaml says slot {MY_SLOT} (picks "
                      f"{my_schedule[:3]}), but this draft gives you "
                      f"{owned[:3]} — using the draft.")
            my_schedule = owned
        else:
            # No pick slots published yet, so the draft order cannot be
            # checked; roster attribution still keys off team id and is safe.
            print(f"  ! draft order not published yet — using slot {MY_SLOT} "
                  f"from league.yaml; verify your first pick lands where "
                  f"expected")
    print(f"  Your picks: {', '.join(str(p) for p in my_schedule[:6])}...")
    print(f"\nPolling every {args.interval}s. Draft in your provider as normal; "
          f"Ctrl-C to stop.\n")

    # Absorb anything already drafted before drawing the opening board. On a
    # restart mid-draft the board would otherwise show drafted players as
    # available, and your own roster as empty, until the next poll.
    unmatched = []
    for entry in draft.new_picks(state0):
        was_mine = (entry.get("team_id") == my_team_id
                    if my_team_id is not None
                    else entry["overall"] in my_schedule)
        available, my_roster, row = apply_pick(available, my_roster, entry,
                                               was_mine)
        if row is None and was_mine and entry["position"] not in {"K", "D/ST", "DEF"}:
            unmatched.append(f"#{entry['overall']} {entry['player']}")
        previous = (f"#{entry['overall']} {entry['player']} "
                    f"[{entry['position']}]{'  <- YOU' if was_mine else ''}")
    if len(my_roster) or unmatched:
        print(f"  Resumed mid-draft: {len(my_roster)} of your picks already made")
    if unmatched:
        print(f"  !! {len(unmatched)} of your picks did not match the board "
              f"({', '.join(unmatched)}) — suggestions will undercount your "
              f"roster")

    # Show the opening board straight away. Without this, starting before the
    # draft leaves a blank screen until someone picks.
    opening_next = next((p for p in my_schedule), None)
    if opening_next is not None:
        following = next((p for p in my_schedule if p > opening_next), None)
        made_now = [p for p in state0["picks"]
                    if p.get("playerId", -1) > 0 or p.get("pick_no")]
        start = (max(p.get("overallPickNumber") or p.get("pick_no")
                     for p in made_now) + 1) if made_now else 1
        print(f"Pick #{start} Round{(start - 1) // LEAGUE_SIZE + 1}"
              f"{' ' + on_the_clock.get(start, '') if on_the_clock.get(start) else ''}"
              f"{'  <<< YOU ARE ON THE CLOCK' if start == opening_next else ''}")
        lo, hi = window_for(opening_next, my_schedule)
        show_board(available, my_roster, lo, hi,
                   on_clock=(start == opening_next))
        shown_for = opening_next if start == opening_next else None

    previous = None
    batch: list[str] = []
    shown_for = None
    failures = 0
    silent_polls = 0
    try:
        while True:
            try:
                state = draft.state()
            except Exception as exc:
                # Two hours of polling will meet a blip; losing the session to
                # it means losing every suggestion until someone notices.
                failures += 1
                print(f"[poll failed ({failures}): {exc}] retrying in "
                      f"{args.interval}s", flush=True)
                time.sleep(args.interval)
                continue
            failures = 0

            # ESPN practice drafts never publish picks, and it is not
            # certain a real one publishes while running. But ESPN also
            # reports inProgress the moment the draft room opens, well before
            # anyone picks, so this waits long enough not to fire during the
            # countdown — and repeats, because a real stall stays a problem.
            if state.get("in_progress") and not draft._seen:
                silent_polls += 1
                every = max(int(SILENT_WARN_AFTER / args.interval), 3)
                if silent_polls % every == 0:
                    waited = int(silent_polls * args.interval)
                    print(f"\n   still no picks after {waited}s. Normal if the "
                          f"draft hasn't started.\n"
                          f"   If picks ARE on your screen, ESPN isn't "
                          f"publishing them — stop and run\n"
                          f"   ./run.py draft  to type them in; same board, "
                          f"same numbers.\n", flush=True)
            else:
                silent_polls = 0
            fresh = draft.new_picks(state)
            batch = []
            for entry in fresh:
                mine = (entry.get("team_id") == my_team_id
                        if my_team_id is not None
                        else entry["overall"] in my_schedule)
                available, my_roster, row = apply_pick(
                    available, my_roster, entry, mine)
                if row is not None:
                    note = ""
                elif entry["position"] in {"K", "D/ST", "DEF"}:
                    note = "  (not projected — draft by feel)"
                elif mine:
                    # Dropping one of your own picks would undercount your
                    # roster in every later suggestion, with nothing on screen
                    # to say so.
                    note = "  !! NOT MATCHED — your roster is missing him"
                else:
                    note = "  (not on board)"
                batch.append(f"#{entry['overall']} {entry['player']} "
                             f"[{entry['position']}]"
                             f"{'  <- YOU' if mine else ''}{note}")

            if state["complete"]:
                print("\ndraft complete")
                break

            # Raw provider picks use their own key names; only the normalised
            # dicts from new_picks() carry "overall".
            made = {
                p.get("overallPickNumber") or p.get("pick_no")
                for p in state["picks"]
                if p.get("playerId", -1) > 0 or p.get("pick_no")
            }
            made.discard(None)
            next_overall = (max(made) + 1) if made else 1
            on_clock = next_overall in my_schedule

            # The board only changes when a pick lands, so recompute once per
            # batch rather than once per pick — reconnecting mid-draft would
            # otherwise rebuild it for every pick already made — and not at
            # all on polls that found nothing.
            if fresh or (on_clock and shown_for != next_overall):
                # A pick is only visible once it has been made, so the header
                # names the team now on the clock and the player who just went.
                # Several can land between polls — list them all rather than
                # letting the earlier ones vanish behind the latest.
                if len(batch) == 1:
                    print(f"Previous Pick: {batch[0]}")
                elif len(batch) > 1:
                    print("Previous Picks:")
                    for line in batch:
                        print(f"  {line}")
                elif previous:
                    print(f"Previous Pick: {previous}")
                if batch:
                    previous = batch[-1]
                rnd = (next_overall - 1) // LEAGUE_SIZE + 1
                team = on_the_clock.get(next_overall, "")
                tag = "  <<< YOU ARE ON THE CLOCK" if on_clock else ""
                print(f"Pick #{next_overall} Round{rnd}"
                      f"{' ' + team if team else ''}{tag}", flush=True)

                # VONA always answers the decision you face at your own next
                # pick. While waiting, the board is first projected forward to
                # that pick, so the fallback it names is one that plausibly
                # survives rather than a player already gone by then.
                mine_next = next((p for p in my_schedule if p >= next_overall), None)
                if mine_next is not None:
                    start, end = window_for(mine_next, my_schedule)
                    show_board(available, my_roster, start, end,
                               on_clock=on_clock)
                if on_clock:
                    shown_for = next_overall

            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nstopped")

    if len(my_roster):
        print_final_roster(my_roster)
    return 0


INDENT = "    "


def indent(text: str) -> str:
    return "\n".join(INDENT + line for line in text.splitlines())


def show_board(available, my_roster, current_pick, next_pick, on_clock=False):
    """Top-ten board and the top of each position, over one shared window.

    VONA answers a single question throughout: what does waiting until your
    next opportunity cost. While others pick, that opportunity is your turn,
    so the window runs from now until then. On the clock it is the pick after
    this one. Both tables use that window and the live board, so a player's
    number in the list is the same number the panel shows for his position.
    """
    sugg = suggest_top(available, my_roster, k=LEAGUE.suggestions,
                       current_pick=current_pick, next_pick=next_pick)
    if sugg.empty:
        print(indent("no candidates left"))
        return

    view = sugg[["Player", "Position", POINTS_COL, "VOR", "MarginalGain",
                 "VONA"]].rename(columns={POINTS_COL: "AVG",
                                          "MarginalGain": "Gain",
                                          "Position": "Pos"})
    view.index = range(1, len(view) + 1)
    print(indent(table_mod.render(view, index_name="#")))

    panel = vona_mod.summary(available, HISTORY, LEAGUE_SIZE,
                             current_pick, next_pick, POINTS_COL)
    if not panel.empty:
        print()
        print(indent("top available at every position"))
        print(indent(table_mod.render(panel)))
    print(indent(f"[{pretty_roster_summary(my_roster)}]"))
    print()


def print_final_roster(my_roster):
    starters_idx = best_starting_lineup_indices(my_roster)
    starters = my_roster.loc[list(starters_idx)]
    bench = my_roster.drop(index=list(starters_idx), errors="ignore")
    cols = ["Player", "Position", POINTS_COL, "VOR"]
    print("\nYour Starters")
    print(indent(table_mod.render(
        starters.sort_values(["Position", POINTS_COL], ascending=[True, False])[cols]
        .rename(columns={POINTS_COL: "AVG", "Position": "Pos"}))))
    if not bench.empty:
        print("\nBench")
        print(indent(table_mod.render(
            bench.sort_values(["VOR", POINTS_COL], ascending=[False, False])[cols]
            .rename(columns={POINTS_COL: "AVG", "Position": "Pos"}))))


def main():
    args = parse_args()
    if args.live:
        return run_live(args)
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

        team = vona_mod.pick_to_team(pick, LEAGUE_SIZE)
        me = (team == MY_SLOT)

        print(f"\n--- Pick #{pick} --- ")

        start, end = window_for(
            next((p for p in my_schedule if p >= pick), pick), my_schedule)
        sugg = suggest_top(available, my_roster, k=LEAGUE.suggestions,
                           current_pick=start, next_pick=end)
        if sugg.empty:
            print("No candidates to suggest.")
            break
        show_board(available, my_roster, start, end, on_clock=me)

        if me:
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

            row, options = resolve_typed(available, user_in)
            if row is None:
                if len(options):
                    print("  did you mean:")
                    for _, o in options.iterrows():
                        print(f"    {o['Player']} ({o['Position']})")
                else:
                    print("  no match — try more of the name")
                continue

            my_roster = pd.concat([my_roster, row.to_frame().T], ignore_index=True)
            available = available[available["Key"] != row["Key"]].reset_index(drop=True)

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

            row, options = resolve_typed(available, key)
            if row is None:
                if len(options):
                    print("  did you mean:")
                    for _, o in options.iterrows():
                        print(f"    {o['Player']} ({o['Position']})")
                else:
                    print("  no match — try more of the name, or 'auto'")
                continue

            available = available[available["Key"] != row["Key"]].reset_index(drop=True)

            if HAVE_PT:
                base_completer.words = remaining_display(available)

            print(f"Team {team} drafted: {row['Player']} ({row['Position']})")
            pick += 1

    if len(my_roster):
        print_final_roster(my_roster)
    return 0


if __name__ == "__main__":
    raise SystemExit(main() or 0)
