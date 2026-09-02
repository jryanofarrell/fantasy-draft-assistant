"""FantasyPros expert consensus rankings.

FantasyPros publishes *rankings*, not point projections — their projections
pages show only ten players without a subscription. Ranks can't be averaged
into a points board, and inventing points from a rank would be fabrication,
so this is treated as enrichment: ECR rank, tier, bye week and the spread of
expert opinion get attached to the consensus rather than folded into it.

Tiers are the genuinely additive part. They mark where the drop-offs are,
which a points board only implies.
"""
from __future__ import annotations

import json
import re

import pandas as pd
import requests

NAME = "fantasypros"

CHEATSHEETS = {
    "standard": "consensus-cheatsheets.php",
    "half_ppr": "half-point-ppr-cheatsheets.php",
    "ppr": "ppr-cheatsheets.php",
}
URL = "https://www.fantasypros.com/nfl/rankings/{slug}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/537.36"
}
# The rankings are rendered client-side from a JSON blob in the page source.
ECR_RE = re.compile(r"ecrData\s*=\s*(\{.*?\})\s*;", re.S)


def fetch_ranks(scoring: str) -> pd.DataFrame:
    """ECR rankings for one scoring format."""
    slug = CHEATSHEETS.get(scoring)
    if slug is None:
        return pd.DataFrame()

    html = requests.get(URL.format(slug=slug), headers=HEADERS, timeout=45).text
    match = ECR_RE.search(html)
    if not match:
        raise RuntimeError(
            "FantasyPros page carried no ecrData blob — their page layout "
            "has probably changed"
        )
    data = json.loads(match.group(1))

    rows = []
    for player in data.get("players", []):
        rows.append({
            "Player": player.get("player_name", ""),
            "Team": player.get("player_team_id", ""),
            "Position": re.sub(r"\d+$", "", str(player.get("pos_rank") or "")) or
                        player.get("player_position_id", ""),
            "ecr": player.get("rank_ecr"),
            "tier": player.get("tier"),
            "pos_rank": player.get("pos_rank"),
            "bye": player.get("player_bye_week"),
            # How much the experts disagree: useful next to our own `spread`.
            "ecr_stdev": player.get("rank_std"),
            "pct_rostered": player.get("player_owned_avg"),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for col in ["ecr", "tier", "ecr_stdev", "pct_rostered"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["ecr"]).reset_index(drop=True)


def experts(scoring: str) -> int | None:
    """How many experts fed the consensus, for provenance."""
    slug = CHEATSHEETS.get(scoring)
    if slug is None:
        return None
    html = requests.get(URL.format(slug=slug), headers=HEADERS, timeout=45).text
    match = ECR_RE.search(html)
    return json.loads(match.group(1)).get("total_experts") if match else None
