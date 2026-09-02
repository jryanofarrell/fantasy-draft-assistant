"""Settings and paths, sourced from `league.yaml`.

Edit `league.yaml`, not this file. These module-level names exist so the
draft scripts can keep importing plain constants.
"""
from pathlib import Path

import league as _league

LEAGUE = _league.load()

# ===== Season =====
SEASON = LEAGUE.season

# ===== League & lineup =====
LEAGUE_SIZE = LEAGUE.size
MY_SLOT = LEAGUE.my_slot
ROSTER_SLOTS = LEAGUE.drafted_slots
FLEX_ELIGIBLE = LEAGUE.flex_eligible
BENCH_SLOTS = LEAGUE.bench
POINTS_COL = LEAGUE.points_column
POSITIONS = LEAGUE.positions

# ===== Files =====
REPO_ROOT = Path(__file__).parent
FILE_TEMPLATE = "{pos}-Table 1.csv"


def data_dir(season: int = SEASON) -> Path:
    """Directory holding a season's projection sheets."""
    return REPO_ROOT / "data" / str(season)


def position_file(pos: str, season: int = SEASON) -> Path:
    """Path to one position's projection sheet for a season."""
    return data_dir(season) / FILE_TEMPLATE.format(pos=pos)
