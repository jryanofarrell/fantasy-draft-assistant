"""Follow a draft as it happens.

Typing every one of the other eleven managers' picks is the part of using a
draft assistant that actually loses you time on the clock. Both ESPN and
Sleeper expose the pick list to anyone who can read the draft, so this polls
it and reports picks as they land.

    ./run.py live                            # your ESPN league, from auth
    ./run.py live --league-id 987654         # an ESPN mock lobby
    ./run.py live --provider sleeper --draft-id 1234567890

ESPN pre-creates every pick slot with playerId -1 and fills it in as the
draft runs, so a pick is "made" once its playerId turns positive.
"""
from __future__ import annotations

import argparse
import sys
import time

import requests

from config import SEASON
from league import import_espn_league as espn_api

ESPN_POSITIONS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}
SLEEPER_DRAFT = "https://api.sleeper.app/v1/draft/{draft_id}"


class DraftClosed(RuntimeError):
    """The draft finished, or the provider stopped returning picks."""


class EspnDraft:
    """Polls an ESPN league's draft, mock or real."""

    def __init__(self, league_id: str, season: int = SEASON):
        auth = espn_api.read_auth()
        self.league_id = league_id or auth.get("ESPN_LEAGUE_ID")
        self.season = season
        self.cookies = {
            "espn_s2": auth.get("ESPN_S2", ""),
            "SWID": auth.get("ESPN_SWID", ""),
        }
        self.url = (
            f"{espn_api.BASE}/seasons/{season}/segments/0/leagues/{self.league_id}"
        )
        self._names: dict[int, tuple[str, str]] = {}
        self._seen: set[int] = set()

    def _resolve(self, player_ids: list[int]) -> None:
        """Look up any player ids we haven't named yet."""
        missing = [p for p in player_ids if p not in self._names and p > 0]
        if not missing:
            return
        resp = requests.get(
            f"{espn_api.BASE}/seasons/{self.season}/players",
            headers={**espn_api.HEADERS,
                     "x-fantasy-filter": '{"players":{"limit":5000}}'},
            cookies=self.cookies,
            params=[("view", "players_wl")],
            timeout=60,
        )
        resp.raise_for_status()
        for entry in resp.json():
            self._names[entry["id"]] = (
                entry.get("fullName", ""),
                ESPN_POSITIONS.get(entry.get("defaultPositionId"), "?"),
            )

    def state(self) -> dict:
        resp = requests.get(
            self.url, headers=espn_api.HEADERS, cookies=self.cookies,
            params=[("view", "mDraftDetail"), ("view", "mTeam")], timeout=30,
        )
        if resp.status_code == 401:
            raise DraftClosed("not authorised to read this draft — check auth")
        resp.raise_for_status()
        payload = resp.json()
        detail = payload.get("draftDetail", {})
        return {
            "in_progress": detail.get("inProgress", False),
            "complete": detail.get("drafted", False),
            "picks": detail.get("picks", []),
            "teams": {t["id"]: (t.get("name") or f"Team {t['id']}").strip()
                      for t in payload.get("teams", [])},
        }

    def new_picks(self) -> list[dict]:
        """Picks made since the last call, oldest first."""
        state = self.state()
        made = [p for p in state["picks"] if p.get("playerId", -1) > 0]
        fresh = [p for p in made if p["overallPickNumber"] not in self._seen]
        if not fresh:
            return []
        self._resolve([p["playerId"] for p in fresh])
        out = []
        for pick in sorted(fresh, key=lambda p: p["overallPickNumber"]):
            self._seen.add(pick["overallPickNumber"])
            name, position = self._names.get(pick["playerId"], ("?", "?"))
            out.append({
                "overall": pick["overallPickNumber"],
                "round": pick.get("roundId"),
                "team": state["teams"].get(pick.get("teamId"), pick.get("teamId")),
                "team_id": pick.get("teamId"),
                "player": name,
                "position": position,
            })
        return out


class SleeperDraft:
    """Polls a Sleeper draft. Public — no credentials needed."""

    def __init__(self, draft_id: str):
        self.draft_id = draft_id
        self._seen: set[int] = set()

    def state(self) -> dict:
        info = requests.get(SLEEPER_DRAFT.format(draft_id=self.draft_id),
                            timeout=30)
        if info.status_code == 404:
            raise DraftClosed(f"no Sleeper draft {self.draft_id}")
        info.raise_for_status()
        meta = info.json()
        picks = requests.get(
            SLEEPER_DRAFT.format(draft_id=self.draft_id) + "/picks", timeout=30
        ).json()
        return {
            "in_progress": meta.get("status") == "drafting",
            "complete": meta.get("status") == "complete",
            "picks": picks or [],
            "teams": {},
        }

    def new_picks(self) -> list[dict]:
        state = self.state()
        fresh = [p for p in state["picks"] if p.get("pick_no") not in self._seen]
        out = []
        for pick in sorted(fresh, key=lambda p: p.get("pick_no", 0)):
            self._seen.add(pick["pick_no"])
            meta = pick.get("metadata") or {}
            name = f"{meta.get('first_name','')} {meta.get('last_name','')}".strip()
            out.append({
                "overall": pick.get("pick_no"),
                "round": pick.get("round"),
                "team": f"Roster {pick.get('roster_id')}",
                "team_id": pick.get("roster_id"),
                "player": name,
                "position": meta.get("position", "?"),
            })
        return out


def connect(provider: str, league_id: str | None, draft_id: str | None,
            season: int = SEASON):
    if provider == "sleeper":
        if not draft_id:
            raise SystemExit("sleeper needs --draft-id")
        return SleeperDraft(draft_id)
    return EspnDraft(league_id, season)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", choices=["espn", "sleeper"], default="espn")
    ap.add_argument("--league-id", help="ESPN league or mock-lobby id")
    ap.add_argument("--draft-id", help="Sleeper draft id")
    ap.add_argument("--season", type=int, default=SEASON)
    ap.add_argument("--interval", type=float, default=5.0,
                    help="seconds between polls")
    ap.add_argument("--once", action="store_true", help="print state and exit")
    args = ap.parse_args()

    try:
        draft = connect(args.provider, args.league_id, args.draft_id, args.season)
        state = draft.state()
    except DraftClosed as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    made = len([p for p in state["picks"]
                if p.get("playerId", 0) > 0 or p.get("pick_no")])
    print(f"{args.provider}: in_progress={state['in_progress']} "
          f"complete={state['complete']} picks_made={made}")
    if args.once:
        for pick in draft.new_picks():
            print(f"  #{pick['overall']:<3} R{pick['round']:<2} "
                  f"{str(pick['team'])[:18]:<18} {pick['player']} ({pick['position']})")
        return 0

    print(f"polling every {args.interval}s — Ctrl-C to stop\n")
    try:
        while True:
            for pick in draft.new_picks():
                print(f"#{pick['overall']:<3} R{pick['round']:<2} "
                      f"{str(pick['team'])[:18]:<18} "
                      f"{pick['player']} ({pick['position']})", flush=True)
            if draft.state()["complete"]:
                print("\ndraft complete")
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nstopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
