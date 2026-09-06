"""Settings and paths, sourced from `league/league.yaml`.

Edit `league.yaml`, not this file. These module-level names exist so the
draft scripts can keep importing plain constants.
"""
from pathlib import Path

from league import league as _league

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

# ===== Scoring formats =====
# Folder names match league.yaml's scoring_type vocabulary.
SCORING_FORMATS = ("standard", "half_ppr", "ppr")
SCORING = LEAGUE.scoring_type

# Points awarded per reception in each format, used to convert between them.
RECEPTION_POINTS = {"standard": 0.0, "half_ppr": 0.5, "ppr": 1.0}

# ===== Files =====
REPO_ROOT = Path(__file__).resolve().parent
FILE_TEMPLATE = "{pos}-Table 1.csv"


def data_dir(season: int = SEASON) -> Path:
    """Root directory for a season's data."""
    return REPO_ROOT / "data" / str(season)


def scoring_dir(scoring: str = SCORING, season: int = SEASON) -> Path:
    """Directory holding the consensus sheets for one scoring format."""
    if scoring not in SCORING_FORMATS:
        raise ValueError(
            f"unknown scoring format {scoring!r}; expected one of "
            f"{list(SCORING_FORMATS)}"
        )
    return data_dir(season) / scoring


def source_dir(source: str, scoring: str = SCORING, season: int = SEASON) -> Path:
    """Directory holding one source's raw sheets for a scoring format."""
    return scoring_dir(scoring, season) / "sources" / source


def position_file(
    pos: str, season: int = SEASON, scoring: str = SCORING, source: str | None = None
) -> Path:
    """Path to one position's sheet.

    Without a source this is the consensus sheet the draft tools read; with
    one it is that source's raw sheet.
    """
    base = source_dir(source, scoring, season) if source else scoring_dir(scoring, season)
    return base / FILE_TEMPLATE.format(pos=pos)
