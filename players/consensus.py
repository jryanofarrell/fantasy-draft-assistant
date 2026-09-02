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

from players.names import fallback_key, normalize_name, player_key

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
        if group["source"].duplicated().any():
            raise AssertionError(
                f"consensus merged two players into {key!r}: sources "
                f"{sorted(group['source'])} — name reconciliation is wrong"
            )
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


def _first_names_compatible(a: str, b: str) -> bool:
    """Whether two first names plausibly refer to the same person.

    "chris"/"christopher" and "kenny"/"kenneth" should merge; "bijan"/"brian"
    must not, even though they share an initial. Requiring a three-character
    common prefix separates the two cases.
    """
    if a == b:
        return True
    if a.startswith(b) or b.startswith(a):
        return True
    common = 0
    for x, y in zip(a, b):
        if x != y:
            break
        common += 1
    return common >= 3


def _reconcile_nicknames(stacked: pd.DataFrame) -> pd.Series:
    """Merge keys that differ only by a nickname spelling.

    Exact-name matching misses "Chris" vs "Christopher". A looser key of
    first initial + last name + position + team catches those, but is too
    loose on its own — Bijan and Brian Robinson are different Atlanta backs
    sharing all four. Two guards keep it honest: first names must share a
    three-character prefix, and folding is rejected if it would put the same
    source in a group twice, since one source does not list one player under
    two spellings.
    """
    keys = stacked["key"].copy()
    loose = [
        fallback_key(n, p, t)
        for n, p, t in zip(stacked["Player"], stacked["Position"], stacked["Team"])
    ]
    stacked = stacked.assign(_loose=loose)

    first_name = {}
    sources_for = {}
    for key, group in stacked.groupby("key", sort=False):
        parts = normalize_name(group["Player"].iloc[0]).split()
        first_name[key] = parts[0] if parts else ""
        sources_for[key] = set(group["source"])

    canonical: dict[str, str] = {}
    for loose_key, group in stacked.groupby("_loose", sort=False):
        if not loose_key:
            continue
        variants = list(group["key"].unique())
        if len(variants) < 2:
            continue
        # Fold onto whichever spelling the most sources agree on.
        winner = max(variants, key=lambda k: len(sources_for[k]))
        held = set(sources_for[winner])
        for variant in variants:
            if variant == winner:
                continue
            if not _first_names_compatible(first_name[variant], first_name[winner]):
                continue
            if held & sources_for[variant]:
                # Same source lists both spellings, so they are two players.
                continue
            canonical[variant] = winner
            held |= sources_for[variant]

    return keys.map(lambda k: canonical.get(k, k))


def enrich(board: pd.DataFrame, ranks: pd.DataFrame) -> pd.DataFrame:
    """Attach ECR rank, tier and bye week to a finished consensus board.

    Joined on the same normalised key as the sources, so nickname spellings
    line up here too. Players the ranker doesn't cover keep empty columns
    rather than being dropped.
    """
    if board.empty or ranks is None or ranks.empty:
        return board

    extra = ranks.copy()
    extra["key"] = [
        player_key(n, p) for n, p in zip(extra["Player"], extra["Position"])
    ]
    extra = extra.drop_duplicates("key")
    keep = [c for c in ["ecr", "tier", "pos_rank", "bye", "ecr_stdev",
                        "pct_rostered"] if c in extra.columns]

    merged = board.copy()
    merged["key"] = [
        player_key(n, p) for n, p in zip(merged["Player"], merged["Position"])
    ]
    merged = merged.merge(extra[["key", *keep]], on="key", how="left")
    return merged.drop(columns="key")


def coverage(by_source: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """How many players each source contributes, per position."""
    rows = []
    for source, df in by_source.items():
        if df is None or df.empty:
            continue
        for position, count in df["Position"].value_counts().items():
            rows.append({"source": source, "Position": position, "players": count})
    return pd.DataFrame(rows)
