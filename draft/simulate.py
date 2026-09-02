"""Dry-run a draft against the real board, to see the live display.

Generates picks instead of reading them from a provider, so you can watch
exactly what `./run.py draft --live` will print before draft day. Other teams
pick the way this league historically has: a position drawn from that round's
observed rates, then the best player left at it.

    ./run.py simulate --picks 30
    ./run.py simulate --picks 30 --seed 7

It is a rehearsal, not a forecast — the other managers are a model of the
league's tendencies, not the managers themselves.
"""
from __future__ import annotations

import argparse
import random

from config import LEAGUE_SIZE, POSITIONS, SEASON
from league.draft_history import rates_for_round


class SimulatedDraft:
    """Stands in for a live provider, revealing one generated pick at a time."""

    def __init__(self, board, history, teams: int, my_team_id: int,
                 team_names: dict, order: list[int], seed: int = 0):
        self.board = board.sort_values("AVG", ascending=False).reset_index(drop=True)
        self.history = history
        self.teams = teams
        self.my_team_id = my_team_id
        self.team_names = team_names
        self.order = order
        self.rng = random.Random(seed)
        self.taken: set[str] = set()
        self.picks: list[dict] = []
        self._seen: set[int] = set()

    def prefetch(self) -> None:
        pass

    def my_team_id_(self):
        return self.my_team_id

    def _choose(self, overall: int) -> dict | None:
        """One team's pick: a position from this round's rates, best player at it."""
        rnd = (overall - 1) // self.teams + 1
        rates = {p: r for p, r in rates_for_round(self.history, rnd).items()
                 if p in POSITIONS}
        left = self.board[~self.board["Player"].isin(self.taken)]
        if left.empty:
            return None

        position = None
        if rates and sum(rates.values()) > 0:
            names, weights = zip(*rates.items())
            for _ in range(6):                      # retry if the pool is empty
                choice = self.rng.choices(names, weights=weights)[0]
                if not left[left["Position"] == choice].empty:
                    position = choice
                    break
        pool = left if position is None else left[left["Position"] == position]
        row = pool.iloc[0]
        self.taken.add(row["Player"])
        seat = (overall - 1) % self.teams
        team_id = self.order[seat if rnd % 2 == 1 else self.teams - 1 - seat]
        return {"overallPickNumber": overall, "roundId": rnd, "teamId": team_id,
                "playerId": overall, "player": row["Player"],
                "position": row["Position"]}

    def slot_owner(self, overall: int) -> int:
        rnd = (overall - 1) // self.teams + 1
        seat = (overall - 1) % self.teams
        return self.order[seat if rnd % 2 == 1 else self.teams - 1 - seat]

    def state(self) -> dict:
        nxt = len(self.picks) + 1
        pick = self._choose(nxt)
        if pick:
            self.picks.append(pick)
        # Expose every remaining slot so the header can name who is up next,
        # matching ESPN, which pre-creates all of them.
        rounds = 15
        future = [{"overallPickNumber": n, "roundId": (n - 1)//self.teams + 1,
                   "teamId": self.slot_owner(n), "playerId": -1}
                  for n in range(len(self.picks) + 1, self.teams * rounds + 1)]
        return {"in_progress": True, "complete": pick is None,
                "picks": list(self.picks) + future,
                "teams": dict(self.team_names), "teams_raw": []}

    def new_picks(self, state=None) -> list[dict]:
        state = state if state is not None else self.state()
        out = []
        for pick in state["picks"]:
            # Unmade slots are placeholders for the header, not picks.
            if "player" not in pick or pick["overallPickNumber"] in self._seen:
                continue
            self._seen.add(pick["overallPickNumber"])
            out.append({
                "overall": pick["overallPickNumber"], "round": pick["roundId"],
                "team": self.team_names.get(pick["teamId"], f"Team {pick['teamId']}"),
                "team_id": pick["teamId"], "player": pick["player"],
                "position": pick["position"],
            })
        return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--picks", type=int, default=30, help="how many picks to run")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--season", type=int, default=SEASON)
    args = ap.parse_args()

    # Imported here so the module can be described without loading the board.
    import draft.draft_assistant as assistant
    from draft import live as live_mod
    from league import import_espn_league as espn_api
    import requests

    auth = espn_api.read_auth()
    cookies = {"espn_s2": auth.get("ESPN_S2", ""), "SWID": auth.get("ESPN_SWID", "")}
    payload = requests.get(
        f"{espn_api.BASE}/seasons/{args.season}/segments/0/leagues/{auth['ESPN_LEAGUE_ID']}",
        headers=espn_api.HEADERS, cookies=cookies,
        params=[("view", "mSettings"), ("view", "mTeam")], timeout=30).json()
    names = {t["id"]: (t.get("name") or f"Team {t['id']}").strip()
             for t in payload.get("teams", [])}
    order = payload["settings"]["draftSettings"]["pickOrder"]
    swid = auth.get("ESPN_SWID", "").strip("{}").lower()
    me = next((t["id"] for t in payload.get("teams", [])
               if swid in [str(o).strip("{}").lower() for o in (t.get("owners") or [])]),
              int(auth.get("ESPN_TEAM_ID", 0)))

    sim = SimulatedDraft(assistant.ranked_overall, assistant.HISTORY, LEAGUE_SIZE,
                         me, names, order, seed=args.seed)

    # Feed the simulation through the real live loop, stopping after N picks.
    live_mod.connect = lambda *a, **k: sim
    assistant.live_mod.connect = lambda *a, **k: sim
    assistant.time.sleep = lambda s: None
    original_state = sim.state

    def capped_state():
        if len(sim.picks) >= args.picks:
            return {"in_progress": False, "complete": True,
                    "picks": list(sim.picks), "teams": dict(names),
                    "teams_raw": []}
        return original_state()

    sim.state = capped_state
    print(f"### SIMULATED DRAFT — {args.picks} picks, seed {args.seed} ###")
    print("### other teams modelled from league history; not a forecast ###")
    return assistant.run_live(assistant.parse_args(["--live"])) or 0


if __name__ == "__main__":
    raise SystemExit(main())
