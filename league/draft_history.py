"""Positional draft tendencies from this league's own past drafts.

National ADP describes three thousand strangers. What matters at your pick is
what *these* managers do, and ESPN keeps every draft the league has ever run.
This pulls those, resolves each pick to a position, and reduces them to a
positional share per round — the input VONA needs to estimate how many players
at a position vanish before your next pick.

Rates are cached to disk because ESPN is slow and the answer changes once a
year, not once a run.
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

import requests

from config import REPO_ROOT, SEASON
from league import import_espn_league as espn_api

CACHE = REPO_ROOT / "league" / "draft_history.json"

# ESPN's defaultPositionId -> position label.
POSITION_IDS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}
DEFAULT_SEASONS = 5


def _player_positions(season: int, cookies: dict) -> dict[int, str]:
    """Position of every player in one season's ESPN universe.

    Resolved per season rather than from a current-day player list, because
    a current list silently drops everyone who has since retired — which
    skews old drafts toward whoever is still playing.
    """
    resp = requests.get(
        f"{espn_api.BASE}/seasons/{season}/players",
        headers={**espn_api.HEADERS, "x-fantasy-filter": '{"players":{"limit":5000}}'},
        cookies=cookies,
        params=[("view", "players_wl")],
        timeout=60,
    )
    resp.raise_for_status()
    return {
        p["id"]: POSITION_IDS.get(p.get("defaultPositionId"), "?")
        for p in resp.json()
    }


def fetch(seasons: list[int] | None = None) -> dict:
    """Pull past drafts and reduce them to positional shares per round."""
    auth = espn_api.read_auth()
    league_id = auth.get("ESPN_LEAGUE_ID")
    if not (league_id and auth.get("ESPN_S2")):
        raise RuntimeError("draft history needs ESPN_LEAGUE_ID and ESPN_S2 in auth")
    cookies = {"espn_s2": auth["ESPN_S2"], "SWID": auth.get("ESPN_SWID", "")}

    if seasons is None:
        settings = requests.get(
            f"{espn_api.BASE}/seasons/{SEASON}/segments/0/leagues/{league_id}",
            headers=espn_api.HEADERS, cookies=cookies,
            params=[("view", "mSettings")], timeout=30,
        ).json()
        previous = sorted(settings.get("status", {}).get("previousSeasons", []))
        seasons = previous[-DEFAULT_SEASONS:]

    counts: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    unresolved = total = 0
    used = []
    for season in seasons:
        positions = _player_positions(season, cookies)
        resp = requests.get(
            f"{espn_api.BASE}/seasons/{season}/segments/0/leagues/{league_id}",
            headers=espn_api.HEADERS, cookies=cookies,
            params=[("view", "mDraftDetail")], timeout=30,
        )
        if resp.status_code != 200:
            continue
        picks = resp.json().get("draftDetail", {}).get("picks", [])
        if not picks:
            continue
        used.append(season)
        for pick in picks:
            total += 1
            position = positions.get(pick.get("playerId"), "?")
            if position == "?":
                unresolved += 1
                continue
            counts[pick["roundId"]][position] += 1

    rates = {}
    for rnd, counter in sorted(counts.items()):
        n = sum(counter.values())
        if n:
            rates[str(rnd)] = {pos: round(c / n, 4) for pos, c in counter.items()}

    return {
        "league_id": league_id,
        "seasons": used,
        "picks": total,
        "unresolved": unresolved,
        "rates": rates,
        "sample_per_round": {str(r): sum(c.values()) for r, c in sorted(counts.items())},
    }


def load(refresh: bool = False) -> dict | None:
    """Cached rates, refetching only when asked or when nothing is cached."""
    if CACHE.exists() and not refresh:
        return json.loads(CACHE.read_text())
    try:
        data = fetch()
    except Exception:
        return json.loads(CACHE.read_text()) if CACHE.exists() else None
    CACHE.write_text(json.dumps(data, indent=2))
    return data


def rates_for_round(history: dict | None, rnd: int) -> dict[str, float]:
    """Positional shares for a round, falling back to the deepest known one."""
    if not history:
        return {}
    rates = history.get("rates", {})
    if str(rnd) in rates:
        return rates[str(rnd)]
    known = sorted(int(k) for k in rates)
    return rates[str(known[-1])] if known else {}


def main() -> int:
    data = load(refresh=True)
    if not data:
        print("could not load draft history")
        return 1
    print(f"league {data['league_id']} — seasons {data['seasons']}")
    print(f"{data['picks']} picks, {data['unresolved']} unresolved\n")
    positions = ["RB", "WR", "TE", "QB", "K", "DEF"]
    print(f"{'rd':<4}" + "".join(f"{p:>6}" for p in positions) + "     n")
    for rnd in sorted(data["rates"], key=int):
        row = data["rates"][rnd]
        n = data["sample_per_round"].get(rnd, 0)
        print(f"{rnd:<4}" + "".join(f"{100*row.get(p,0):>5.0f}%" for p in positions) + f"  {n:>4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
