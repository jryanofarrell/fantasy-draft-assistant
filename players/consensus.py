"""Merge per-source projections into a single consensus sheet.

Sources disagree substantially — often 15% on the same player — because each
carries its own biases about volume and touchdown regression. Aggregating
cancels part of that, which is why consensus projections generally beat any
single source.

The median is used rather than the mean: one source with a stale injury
assumption should not drag a player tens of points. Every row records how
many sources contributed and how far apart they were, so a number resting on
a single opinion is visible rather than implied.
"""
from __future__ import annotations

import pandas as pd

from players.names import fallback_key, player_key

# Columns carried through from whichever source supplies them.
PASSTHROUGH = ["injury_status"]


def build(
    by_source: dict[str, pd.DataFrame], min_sources: int = 1
) -> pd.DataFrame:
    """Combine one scoring format's frames into a consensus board.

    `by_source` maps a source name to a frame with Player / Team / Position /
    AVG. Rows backed by fewer than `min_sources` sources are dropped.
    """
    frames = []
    for source, df in by_source.items():
        if df is None or df.empty:
            continue
        frame = df.copy()
        frame["source"] = source
        frame["key"] = [
            player_key(n, p) for n, p in zip(frame["Player"], frame["Position"])
        ]
        frames.append(frame)

    if not frames:
        return pd.DataFrame(
            columns=["Player", "Team", "Position", "AVG", "sources", "spread"]
        )

    stacked = pd.concat(frames, ignore_index=True)
    stacked["AVG"] = pd.to_numeric(stacked["AVG"], errors="coerce")
    stacked = stacked.dropna(subset=["AVG"])
    stacked["key"] = _reconcile_nicknames(stacked)

    rows = []
    for key, group in stacked.groupby("key", sort=False):
        values = group["AVG"]
        # Prefer the longest spelling: sources that keep "Jr." or a full first
        # name are usually the more complete record.
        display = max(group["Player"], key=len)
        teams = [t for t in group["Team"] if t]
        row = {
            "Player": display,
            "Team": teams[0] if teams else "",
            "Position": group["Position"].iloc[0],
            "AVG": round(values.median(), 2),
            "sources": len(group),
            "spread": round(values.max() - values.min(), 2) if len(group) > 1 else 0.0,
        }
        for source in sorted(stacked["source"].unique()):
            match = group.loc[group["source"] == source, "AVG"]
            row[f"AVG_{source}"] = round(match.iloc[0], 2) if len(match) else None
        for col in PASSTHROUGH:
            if col in group.columns:
                present = [v for v in group[col] if isinstance(v, str) and v]
                row[col] = present[0] if present else ""
        rows.append(row)

    out = pd.DataFrame(rows)
    out = out[out["sources"] >= min_sources]
    return out.sort_values("AVG", ascending=False).reset_index(drop=True)


def _reconcile_nicknames(stacked: pd.DataFrame) -> pd.Series:
    """Merge keys that differ only by a nickname spelling.

    Exact-name matching misses "Chris" vs "Christopher" and similar. Where a
    looser key (first initial + last name + position + team) covers several
    exact keys, they are folded onto the one with the most sources — an
    alias table would work too, but only for names someone thought of.
    """
    keys = stacked["key"].copy()
    loose = [
        fallback_key(n, p, t)
        for n, p, t in zip(stacked["Player"], stacked["Position"], stacked["Team"])
    ]
    stacked = stacked.assign(_loose=loose)

    canonical: dict[str, str] = {}
    for loose_key, group in stacked.groupby("_loose", sort=False):
        if not loose_key:
            continue
        variants = group["key"].unique()
        if len(variants) < 2:
            continue
        # Fold onto whichever spelling the most sources agree on.
        winner = group.groupby("key")["source"].nunique().idxmax()
        for variant in variants:
            canonical[variant] = winner

    return keys.map(lambda k: canonical.get(k, k))


def coverage(by_source: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """How many players each source contributes, per position."""
    rows = []
    for source, df in by_source.items():
        if df is None or df.empty:
            continue
        for position, count in df["Position"].value_counts().items():
            rows.append({"source": source, "Position": position, "players": count})
    return pd.DataFrame(rows)
