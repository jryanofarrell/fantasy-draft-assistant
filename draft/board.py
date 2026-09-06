"""Loading projections and computing replacement levels.

Both the draft assistant and the standalone rankings need the same board:
the same sheets, cleaned the same way, measured against the same replacement
lines. They each had their own copy, and the copies had drifted — one
stripped thousands separators out of the points column before parsing and
the other did not, so a value that read fine in one silently became NaN and
vanished in the other.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import (
    FLEX_ELIGIBLE,
    LEAGUE_SIZE,
    POINTS_COL,
    POSITIONS,
    ROSTER_SLOTS,
    SCORING,
    SEASON,
    position_file,
)

# Values pandas shouldn't treat as data. The mojibake entries are what a
# spreadsheet's non-breaking spaces become on export.
NA_VALUES = ["NaN", "nan", "", " ", "Â", "Â\xa0"]


def load_positions(season: int = SEASON, scoring: str = SCORING) -> dict[str, pd.DataFrame]:
    """One cleaned, points-sorted frame per position."""
    frames = {}
    for pos in POSITIONS:
        df = pd.read_csv(position_file(pos, season, scoring),
                         na_values=NA_VALUES, keep_default_na=True)
        df = df.dropna(subset=["Player"]).copy()
        df["Player"] = df["Player"].astype(str).str.strip()
        # Points can arrive with thousands separators or stray symbols.
        df[POINTS_COL] = (
            df[POINTS_COL].astype(str)
            .str.replace(",", "", regex=False)
            .str.replace(r"[^\d\.\-]", "", regex=True)
            .replace({"": np.nan})
        )
        df[POINTS_COL] = pd.to_numeric(df[POINTS_COL], errors="coerce")
        df = df.dropna(subset=[POINTS_COL])
        df = df.sort_values(POINTS_COL, ascending=False).reset_index(drop=True)
        df["Position"] = pos
        frames[pos] = df
    return frames


def compute_replacements(
    frames: dict[str, pd.DataFrame],
    league_size: int = LEAGUE_SIZE,
    roster_slots: dict[str, int] | None = None,
    flex_eligible: set[str] | None = None,
) -> tuple[dict[str, float], dict[str, int], dict[str, int]]:
    """Replacement-level points per position, after allocating FLEX.

    Every team starts the same core slots, so the replacement player at a
    position is the one just past what the league collectively starts there.
    FLEX slots then go, one at a time, to whichever eligible position has the
    best player still unclaimed — a k-way merge that pushes those positions
    deeper in proportion to how much the league actually leans on them.
    """
    roster_slots = ROSTER_SLOTS if roster_slots is None else roster_slots
    flex_eligible = FLEX_ELIGIBLE if flex_eligible is None else flex_eligible

    needed = {p: league_size * roster_slots.get(p, 0) for p in frames}
    index = {}
    for pos, frame in frames.items():
        want = needed.get(pos, 0) - 1
        index[pos] = -1 if frame.empty else max(-1, min(want, len(frame) - 1))

    taken = {p: 0 for p in frames}
    for _ in range(league_size * roster_slots.get("FLEX", 0)):
        candidates = [
            (pos, frames[pos].iloc[index[pos] + 1][POINTS_COL])
            for pos in flex_eligible
            if pos in frames and index[pos] + 1 < len(frames[pos])
        ]
        if not candidates:
            break
        best = max(candidates, key=lambda item: item[1])[0]
        index[best] += 1
        taken[best] += 1

    values = {
        pos: (float(frame.iloc[index[pos]][POINTS_COL])
              if index[pos] >= 0 and len(frame) else -np.inf)
        for pos, frame in frames.items()
    }
    return values, index, taken


def build(season: int = SEASON, scoring: str = SCORING):
    """The full board: every position pooled, with VOR against replacement."""
    frames = load_positions(season, scoring)
    replacement, index, taken = compute_replacements(frames)

    pooled = []
    for pos, frame in frames.items():
        out = frame.copy()
        out["ReplacementAVG"] = replacement[pos]
        out["VOR"] = out[POINTS_COL] - out["ReplacementAVG"]
        pooled.append(out)

    board = pd.concat(pooled, ignore_index=True)
    for col in (POINTS_COL, "VOR", "ReplacementAVG"):
        board[col] = pd.to_numeric(board[col], errors="coerce")
    board = board.sort_values([ "VOR", POINTS_COL], ascending=[False, False])
    board = board.reset_index(drop=True)
    board["Key"] = (
        board["Player"].str.strip() + " (" + board["Position"] + ")"
    ).str.lower()
    return board, frames, replacement, index, taken
