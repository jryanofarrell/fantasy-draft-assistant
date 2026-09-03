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

import json
from pathlib import Path

import requests

from config import SEASON
from league import import_espn_league as espn_api

ESPN_POSITIONS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}
SLEEPER_DRAFT = "https://api.sleeper.app/v1/draft/{draft_id}"


def format_pick(pick: dict) -> str:
    """One line per pick: overall, round, team, player, position."""
    return (f"#{pick['overall']:<3} R{pick['round']:<2} "
            f"{str(pick['team'])[:18]:<18} "
            f"{pick['player']} ({pick['position']})")


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

    def prefetch(self) -> None:
        """Warm the player index so the first pick doesn't stall on a lookup."""
        self._resolve([-1])

    def _resolve(self, player_ids: list[int]) -> None:
        """Look up any player ids we haven't named yet."""
        missing = [p for p in player_ids if p not in self._names and p > 0]
        if not missing and self._names:
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

    def my_team_id(self) -> int | None:
        """Which team the authenticated user owns, by SWID.

        Draft *slot* is re-randomised every season, so identifying your picks
        by slot arithmetic silently mislabels them whenever the configured
        slot doesn't match the season being read. Ownership does not move.
        """
        auth = espn_api.read_auth()
        swid = (auth.get("ESPN_SWID") or "").strip("{}").lower()
        for team in self.state().get("teams_raw", []):
            owners = [str(o).strip("{}").lower() for o in (team.get("owners") or [])]
            if swid and swid in owners:
                return team.get("id")
        team_id = auth.get("ESPN_TEAM_ID")
        return int(team_id) if team_id else None

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
            "teams_raw": payload.get("teams", []),
        }

    def new_picks(self, state: dict | None = None) -> list[dict]:
        """Picks made since the last call, oldest first.

        Accepts an already-fetched state so a polling loop can check for new
        picks and for completion without paying for two requests.
        """
        state = state if state is not None else self.state()
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

    def new_picks(self, state: dict | None = None) -> list[dict]:
        state = state if state is not None else self.state()
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


class LocalDraft:
    """Picks captured from the draft room by the browser bridge.

    ESPN's draft room speaks its own line protocol over a socket that only
    exists in the browser, and publishes nothing to the read API until the
    draft ends. The userscript forwards the picks; this resolves the ids in
    them against ESPN's player index and the league's team names, so the
    assistant sees the same shape it gets from any other provider.
    """

    def __init__(self, feed: str | None = None, season: int = SEASON):
        from config import REPO_ROOT
        self.dir = REPO_ROOT / "bridge" / "feeds"
        # An explicit argument may be a league id or a path; without one the
        # most recently written draft is the one in progress.
        self.explicit = None
        if feed:
            candidate = Path(feed)
            self.explicit = candidate if candidate.exists() else \
                self.dir / f"draft-{feed}.json"
        self.season = season
        self._seen: set[int] = set()
        self._players: dict[int, tuple[str, str]] = {}
        self._teams: dict[int, str] = {}
        self._league_id: str | None = None

    @property
    def path(self) -> Path | None:
        if self.explicit:
            return self.explicit
        feeds = sorted(self.dir.glob("draft-*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        return feeds[0] if feeds else None

    def _cookies(self) -> dict:
        auth = espn_api.read_auth()
        return {"espn_s2": auth.get("ESPN_S2", ""),
                "SWID": auth.get("ESPN_SWID", "")}

    def prefetch(self) -> None:
        """Load ESPN's player index once, so picks resolve instantly."""
        if self._players:
            return
        resp = requests.get(
            f"{espn_api.BASE}/seasons/{self.season}/players",
            headers={**espn_api.HEADERS,
                     "x-fantasy-filter": '{"players":{"limit":8000}}'},
            cookies=self._cookies(), params=[("view", "players_wl")], timeout=60)
        resp.raise_for_status()
        self._players = {
            p["id"]: (p.get("fullName", ""),
                      ESPN_POSITIONS.get(p.get("defaultPositionId"), "?"))
            for p in resp.json()
        }

    def _load_teams(self, league_id: str) -> None:
        if self._teams or not league_id:
            return
        try:
            payload = requests.get(
                f"{espn_api.BASE}/seasons/{self.season}/segments/0/leagues/{league_id}",
                headers=espn_api.HEADERS, cookies=self._cookies(),
                params=[("view", "mTeam")], timeout=30).json()
            self._teams = {t["id"]: (t.get("name") or f"Team {t['id']}").strip()
                           for t in payload.get("teams", [])}
        except Exception:
            self._teams = {}

    def my_team_id(self) -> int | None:
        auth = espn_api.read_auth()
        team_id = auth.get("ESPN_TEAM_ID")
        return int(team_id) if team_id else None

    def state(self) -> dict:
        path = self.path
        if path is None or not path.exists():
            return {"in_progress": False, "complete": False, "picks": [],
                    "teams": {}, "teams_raw": []}
        try:
            data = json.loads(path.read_text() or "{}")
        except json.JSONDecodeError:
            data = {}
        league_id = data.get("leagueId")
        if league_id and league_id != self._league_id:
            if self._league_id is not None:
                # The feed now describes a different draft; anything already
                # reported belongs to the old one.
                print(f"  ! feed switched to league {league_id} — restart the "
                      f"assistant to rebuild the board", flush=True)
            self._league_id = league_id
            self._teams = {}
            self._load_teams(league_id)
        picks = data.get("picks", [])
        return {"in_progress": bool(picks), "complete": bool(data.get("complete")),
                "picks": picks, "teams": dict(self._teams), "teams_raw": []}

    def new_picks(self, state: dict | None = None) -> list[dict]:
        state = state if state is not None else self.state()
        self.prefetch()
        teams_size = max(len(self._teams), 1)
        out = []
        for pick in state["picks"]:
            overall = pick.get("overall")
            if overall is None or overall in self._seen:
                continue
            self._seen.add(overall)
            name, position = self._players.get(pick.get("player_id"), ("?", "?"))
            out.append({
                "overall": overall,
                "round": (overall - 1) // teams_size + 1,
                "team": self._teams.get(pick.get("team_id"),
                                        f"Team {pick.get('team_id')}"),
                "team_id": pick.get("team_id"),
                "player": name,
                "position": position,
            })
        return sorted(out, key=lambda p: p["overall"])


def connect(provider: str, league_id: str | None, draft_id: str | None,
            season: int = SEASON):
    if provider == "local":
        return LocalDraft(league_id, season)
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
        for pick in draft.new_picks(state):
            print("  " + format_pick(pick))
        return 0

    if isinstance(draft, EspnDraft):
        draft.prefetch()

    print(f"polling every {args.interval}s — Ctrl-C to stop\n")
    try:
        while True:
            # One request per cycle: the same state answers both questions.
            state = draft.state()
            for pick in draft.new_picks(state):
                print(format_pick(pick), flush=True)
            if state["complete"]:
                print("\ndraft complete")
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nstopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
