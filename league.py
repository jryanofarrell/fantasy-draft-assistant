"""Load and validate `league.yaml`.

The YAML file is the single source of truth for league settings. This module
reads it, checks the values that would otherwise fail silently and produce a
wrong draft board, and exposes them as a `League` object.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(__file__).parent / "league.yaml"

SCORING_TYPE_RECEPTION = {"standard": 0.0, "half_ppr": 0.5, "ppr": 1.0}


class LeagueConfigError(ValueError):
    """Raised when league.yaml is missing or internally inconsistent."""


@dataclass(frozen=True)
class League:
    season: int
    size: int
    scoring_type: str
    name: str
    draft_type: str
    my_slot: int
    lineup_slots: dict[str, int]
    flex_eligible: set[str]
    op_eligible: set[str]
    bench: int
    ir: int
    scoring: dict[str, Any]
    positions: list[str]
    points_column: str
    suggestions: int
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    # ---- derived ----

    @property
    def reception_points(self) -> float:
        """Points per reception, from scoring.receiving.reception."""
        return float(self.scoring["receiving"]["reception"])

    @property
    def starter_slots(self) -> int:
        """Total starting lineup spots across every position."""
        return sum(self.lineup_slots.values())

    @property
    def roster_size(self) -> int:
        """Starters plus bench (IR is not drafted)."""
        return self.starter_slots + self.bench

    @property
    def drafted_slots(self) -> dict[str, int]:
        """Lineup slots restricted to positions the assistant actually ranks.

        Slots the tool doesn't draft (K, D/ST) are excluded so replacement
        levels aren't computed against positions with no projection data.
        """
        keep = set(self.positions) | {"FLEX"}
        return {k: v for k, v in self.lineup_slots.items() if k in keep and v}

    @property
    def drafted_roster_size(self) -> int:
        """Roster spots the assistant will fill, ignoring K/D-ST slots."""
        undrafted = self.starter_slots - sum(self.drafted_slots.values())
        return self.roster_size - undrafted


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise LeagueConfigError(msg)


def load(path: Path = CONFIG_PATH) -> League:
    """Read league.yaml and validate it."""
    _require(path.exists(), f"League config not found: {path}")
    data = yaml.safe_load(path.read_text()) or {}

    for section in ("league", "draft", "roster", "scoring", "tool"):
        _require(section in data, f"league.yaml is missing the '{section}' section")

    lg, draft, roster, scoring, tool = (
        data["league"], data["draft"], data["roster"], data["scoring"], data["tool"]
    )
    slots = dict(roster["lineup_slots"])
    positions = list(tool["positions"])

    size = int(lg["size"])
    my_slot = int(draft["my_slot"])
    _require(size > 0, "league.size must be positive")
    _require(
        1 <= my_slot <= size,
        f"draft.my_slot ({my_slot}) must be between 1 and league.size ({size})",
    )
    _require(
        draft["type"] == "snake",
        f"draft.type '{draft['type']}' is not implemented — only 'snake' is",
    )

    flex_eligible = set(roster["flex_eligible"])
    _require(
        flex_eligible <= set(positions),
        f"roster.flex_eligible {sorted(flex_eligible - set(positions))} "
        f"are not in tool.positions {positions}",
    )
    _require(
        not slots.get("FLEX") or flex_eligible,
        "roster has FLEX slots but roster.flex_eligible is empty",
    )
    for pos in positions:
        _require(pos in slots, f"tool.positions lists '{pos}' with no lineup slot entry")

    # A scoring_type that disagrees with the reception value is the kind of
    # mistake that silently produces a wrong board, so reject it outright.
    stype = lg["scoring_type"]
    _require(
        stype in SCORING_TYPE_RECEPTION,
        f"league.scoring_type '{stype}' must be one of "
        f"{sorted(SCORING_TYPE_RECEPTION)}",
    )
    reception = float(scoring["receiving"]["reception"])
    expected = SCORING_TYPE_RECEPTION[stype]
    _require(
        reception == expected,
        f"league.scoring_type is '{stype}' (expects "
        f"{expected} pts/reception) but scoring.receiving.reception is "
        f"{reception}. Fix whichever is wrong.",
    )

    return League(
        season=int(lg["season"]),
        size=size,
        scoring_type=stype,
        name=lg.get("name", ""),
        draft_type=draft["type"],
        my_slot=my_slot,
        lineup_slots=slots,
        flex_eligible=flex_eligible,
        op_eligible=set(roster.get("op_eligible", [])),
        bench=int(roster["bench"]),
        ir=int(roster.get("ir", 0)),
        scoring=scoring,
        positions=positions,
        points_column=tool["points_column"],
        suggestions=int(tool.get("suggestions", 10)),
        raw=data,
    )


def summary(lg: League) -> str:
    """One-block description of the loaded league, printed at draft start."""
    starters = ", ".join(f"{k} {v}" for k, v in lg.lineup_slots.items() if v)
    return (
        f"{lg.name or 'League'} — {lg.season}, {lg.size} teams, "
        f"{lg.scoring_type.replace('_', ' ')} ({lg.reception_points} pts/rec)\n"
        f"  Starters: {starters} | Bench: {lg.bench}\n"
        f"  Your slot: {lg.my_slot} of {lg.size} | "
        f"Drafting {lg.drafted_roster_size} players"
    )


if __name__ == "__main__":
    print(summary(load()))
