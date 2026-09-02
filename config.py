"""Shared league and path configuration."""
from pathlib import Path

# ===== Season =====
SEASON = 2026

# ===== League & lineup =====
LEAGUE_SIZE = 12          # change if your league isn't 12 teams
MY_SLOT = 12              # your draft position (1..LEAGUE_SIZE)
ROSTER_SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2}
FLEX_ELIGIBLE = {"RB", "WR", "TE"}
BENCH_SLOTS = 5
POINTS_COL = "AVG"
POSITIONS = ["QB", "RB", "WR", "TE"]

# ===== Files =====
REPO_ROOT = Path(__file__).parent
FILE_TEMPLATE = "{pos}-Table 1.csv"


def data_dir(season: int = SEASON) -> Path:
    """Directory holding a season's projection sheets."""
    return REPO_ROOT / "data" / str(season)


def position_file(pos: str, season: int = SEASON) -> Path:
    """Path to one position's projection sheet for a season."""
    return data_dir(season) / FILE_TEMPLATE.format(pos=pos)
