"""Read live league settings from ESPN and map them onto `league.yaml` shape.

    python import_espn_league.py --league-id 123456
    python import_espn_league.py --league-id 123456 --write

Private leagues (most are) need two cookies from a browser session that is
logged in to ESPN. Copy `auth.example` to `auth` and fill it in; `auth` is
gitignored. Values may also come from the environment or CLI flags, which
take precedence over the file.

By default this only prints what ESPN reports alongside the current config.
`--write` saves the ESPN values to league.espn.yaml for you to review and
merge; it never overwrites league.yaml.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
import yaml

import league as league_mod
from config import SEASON

AUTH_FILE = Path(__file__).parent / "auth"
BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/537.36"
}

# ESPN lineup slot ids -> our roster slot names. Slots we don't model are
# reported but not mapped.
SLOT_MAP = {
    0: "QB",
    2: "RB",
    4: "WR",
    6: "TE",
    23: "FLEX",   # ESPN calls this RB/WR/TE
    7: "OP",      # superflex
    16: "D/ST",
    17: "K",
    20: "BE",
    21: "IR",
}

# ESPN scoring stat ids -> where the value lands in league.yaml.
# "rate" means ESPN gives points-per-yard and we store yards-per-point.
SCORING_MAP = {
    3:  ("passing", "yards_per_point", "rate"),
    4:  ("passing", "touchdown", "flat"),
    95: ("passing", "interception", "flat"),
    19: ("passing", "two_point_conversion", "flat"),
    24: ("rushing", "yards_per_point", "rate"),
    25: ("rushing", "touchdown", "flat"),
    26: ("rushing", "two_point_conversion", "flat"),
    37: ("rushing", "bonus_100_yd", "flat"),
    38: ("rushing", "bonus_200_yd", "flat"),
    53: ("receiving", "reception", "flat"),
    42: ("receiving", "yards_per_point", "rate"),
    43: ("receiving", "touchdown", "flat"),
    44: ("receiving", "two_point_conversion", "flat"),
    56: ("receiving", "bonus_100_yd", "flat"),
    57: ("receiving", "bonus_200_yd", "flat"),
    72: ("misc", "fumble_lost", "flat"),
    63: ("misc", "fumble_recovered_td", "flat"),
    101: ("misc", "return_td", "flat"),
    102: ("misc", "return_td", "flat"),
}

RECEPTION_TO_TYPE = {0.0: "standard", 0.5: "half_ppr", 1.0: "ppr"}


class EspnError(RuntimeError):
    pass


def read_auth(path: Path = AUTH_FILE) -> dict[str, str]:
    """Parse the gitignored `auth` file into a dict. Missing file is fine."""
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip("\'\"")
        if val:
            values[key.strip()] = val
    return values


def setting(name: str, flag: str | None, auth: dict[str, str]) -> str | None:
    """CLI flag beats environment, which beats the auth file."""
    return flag or os.environ.get(name) or auth.get(name)


def fetch(league_id: str, season: int, espn_s2: str | None, swid: str | None) -> dict:
    url = f"{BASE}/seasons/{season}/segments/0/leagues/{league_id}"
    cookies = {}
    if espn_s2 and swid:
        cookies = {"espn_s2": espn_s2, "SWID": swid}
    resp = requests.get(
        url,
        headers=HEADERS,
        cookies=cookies,
        params=[("view", "mSettings"), ("view", "mTeam")],
        timeout=30,
    )
    if resp.status_code == 401:
        raise EspnError(
            "ESPN says you are not authorized to view this league.\n"
            "  If the league is private, pass --espn-s2 and --swid "
            "(or set ESPN_S2 / ESPN_SWID).\n"
            "  If you already did, the cookies may have expired — grab fresh "
            "ones from the browser."
        )
    if resp.status_code == 404:
        raise EspnError(
            f"No league {league_id} in season {season}. Check the leagueId in "
            f"your ESPN URL, and that the season is right."
        )
    resp.raise_for_status()
    return resp.json()


def map_settings(payload: dict, season: int) -> dict[str, Any]:
    """Translate an ESPN settings payload into league.yaml structure."""
    s = payload.get("settings", {})
    roster = s.get("rosterSettings", {})
    draft = s.get("draftSettings", {})
    scoring_items = s.get("scoringSettings", {}).get("scoringItems", [])

    slot_counts = roster.get("lineupSlotCounts", {})
    slots: dict[str, int] = {}
    unmapped: dict[str, int] = {}
    for raw_id, count in slot_counts.items():
        if not count:
            continue
        name = SLOT_MAP.get(int(raw_id))
        if name:
            slots[name] = int(count)
        else:
            unmapped[str(raw_id)] = int(count)

    bench = slots.pop("BE", 0)
    ir = slots.pop("IR", 0)

    scoring: dict[str, dict[str, float]] = {}
    unknown_scoring = []
    for item in scoring_items:
        stat_id = item.get("statId")
        points = item.get("pointsOverrides", {}).get("16", item.get("points", 0))
        target = SCORING_MAP.get(stat_id)
        if target is None:
            if points:
                unknown_scoring.append((stat_id, points))
            continue
        section, key, kind = target
        if kind == "rate":
            # ESPN stores points-per-yard; we store yards-per-point.
            scoring.setdefault(section, {})[key] = (
                round(1 / points) if points else 0
            )
        else:
            scoring.setdefault(section, {})[key] = points

    reception = scoring.get("receiving", {}).get("reception", 0.0)
    scoring_type = RECEPTION_TO_TYPE.get(float(reception))

    return {
        "league": {
            "name": s.get("name", ""),
            "platform": "espn",
            "season": season,
            "size": s.get("size"),
            "scoring_type": scoring_type,
        },
        "draft": {
            "type": "snake" if draft.get("type") == "SNAKE" else draft.get("type"),
            "pick_order": draft.get("pickOrder"),
        },
        "roster": {"lineup_slots": slots, "bench": bench, "ir": ir},
        "scoring": scoring,
        "_unmapped_slots": unmapped,
        "_unknown_scoring": unknown_scoring,
        "_teams": {
            t.get("id"): (t.get("name") or "").strip()
            for t in payload.get("teams", [])
        },
    }


def my_slot(
    mapped: dict, payload: dict, swid: str | None, team_id: int | None = None
) -> int | None:
    """Find the user's draft position, if their team can be identified.

    An explicit team id is used directly; otherwise the SWID is matched
    against each team's owner list.
    """
    order = mapped["draft"].get("pick_order") or []
    if not order:
        return None
    if team_id is not None and team_id in order:
        return order.index(team_id) + 1
    if not swid:
        return None
    target = swid.strip("{}").lower()
    for team in payload.get("teams", []):
        owners = [str(o).strip("{}").lower() for o in team.get("owners", [])]
        if target in owners and team.get("id") in order:
            return order.index(team["id"]) + 1
    return None


def compare(mapped: dict, slot: int | None) -> list[tuple[str, Any, Any, bool]]:
    """Rows of (field, current league.yaml value, ESPN value, differs)."""
    cur = league_mod.load()
    rows: list[tuple[str, Any, Any, bool]] = []

    def add(label: str, current: Any, espn: Any) -> None:
        rows.append((label, current, espn, espn is not None and current != espn))

    add("league.size", cur.size, mapped["league"]["size"])
    add("league.scoring_type", cur.scoring_type, mapped["league"]["scoring_type"])
    add("draft.type", cur.draft_type, mapped["draft"]["type"])
    add("draft.my_slot", cur.my_slot, slot)
    for name in ["QB", "RB", "WR", "TE", "FLEX", "OP", "D/ST", "K"]:
        add(
            f"roster.lineup_slots.{name}",
            cur.lineup_slots.get(name, 0),
            mapped["roster"]["lineup_slots"].get(name, 0),
        )
    add("roster.bench", cur.bench, mapped["roster"]["bench"])
    add("roster.ir", cur.ir, mapped["roster"]["ir"])
    for section, keys in [
        ("passing", ["yards_per_point", "touchdown", "interception"]),
        ("rushing", ["yards_per_point", "touchdown"]),
        ("receiving", ["reception", "yards_per_point", "touchdown"]),
        ("misc", ["fumble_lost"]),
    ]:
        for key in keys:
            add(
                f"scoring.{section}.{key}",
                cur.scoring.get(section, {}).get(key),
                mapped["scoring"].get(section, {}).get(key),
            )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league-id", help="leagueId from your ESPN URL")
    ap.add_argument("--team-id", type=int, help="your teamId, to resolve draft slot")
    ap.add_argument("--season", type=int, default=SEASON)
    ap.add_argument("--espn-s2")
    ap.add_argument("--swid")
    ap.add_argument("--write", action="store_true",
                    help="save ESPN values to league.espn.yaml for review")
    ap.add_argument("--raw", action="store_true", help="dump the raw ESPN payload")
    args = ap.parse_args()

    auth = read_auth()
    espn_s2 = setting("ESPN_S2", args.espn_s2, auth)
    swid = setting("ESPN_SWID", args.swid, auth)
    league_id = setting("ESPN_LEAGUE_ID", args.league_id, auth)
    team_raw = setting("ESPN_TEAM_ID", str(args.team_id) if args.team_id else None, auth)
    team_id = int(team_raw) if team_raw else None

    if not league_id:
        print("error: no league id. Pass --league-id or set ESPN_LEAGUE_ID in "
              "the auth file.", file=sys.stderr)
        return 1
    if swid and not espn_s2:
        print("warning: SWID is set but ESPN_S2 is empty — private leagues need "
              "both. Trying anyway.\n", file=sys.stderr)

    try:
        payload = fetch(league_id, args.season, espn_s2, swid)
    except EspnError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.raw:
        print(json.dumps(payload, indent=2))
        return 0

    mapped = map_settings(payload, args.season)
    slot = my_slot(mapped, payload, swid, team_id)

    name = mapped["league"]["name"] or "(unnamed)"
    print(f"ESPN league {league_id} — {name} ({args.season})\n")

    rows = compare(mapped, slot)
    width = max(len(r[0]) for r in rows)
    print(f"{'field'.ljust(width)}  {'league.yaml':>12}  {'ESPN':>12}")
    print("-" * (width + 30))
    for label, current, espn, differs in rows:
        flag = "  <-- differs" if differs else ""
        shown = "?" if espn is None else espn
        print(f"{label.ljust(width)}  {str(current):>12}  {str(shown):>12}{flag}")

    if slot is None:
        print("\nnote: could not identify your draft slot — set ESPN_TEAM_ID in "
              "the auth file, or the draft order may not be set yet.")
    if mapped["_unmapped_slots"]:
        print(f"\nnote: unmapped lineup slots (ESPN slot id -> count): "
              f"{mapped['_unmapped_slots']}")
    if mapped["_unknown_scoring"]:
        print(f"\nnote: {len(mapped['_unknown_scoring'])} scoring rules with "
              f"non-zero points aren't mapped into league.yaml "
              f"(statId, points): {mapped['_unknown_scoring'][:10]}")

    if args.write:
        out = Path("league.espn.yaml")
        payload_out = {k: v for k, v in mapped.items() if not k.startswith("_")}
        if slot:
            payload_out["draft"]["my_slot"] = slot
        out.write_text(
            "# Imported from ESPN — review, then merge into league.yaml.\n"
            + yaml.safe_dump(payload_out, sort_keys=False)
        )
        print(f"\nwrote {out} (league.yaml untouched)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
