"""Download CBS season projections and write per-position draft sheets.

Produces `data/<season>/<POS>-Table 1.csv` with the `Player` / `AVG` columns
the draft assistant expects, where `AVG` is projected season fantasy points
converted to the league's reception scoring (see `league.yaml`).

    python download_projections.py --season 2026
"""
import argparse
import io
import re

import pandas as pd
import requests
import requests_cache

from config import LEAGUE, POSITIONS, SEASON, data_dir, position_file

URL_TEMPLATE = (
    "https://www.cbssports.com/fantasy/football/stats/"
    "{pos}/{season}/season/projections/ppr/"
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/537.36"
}

# We scrape CBS's PPR pages, which award 1 point per reception.
SOURCE_RECEPTION_POINTS = 1.0

# CBS renders the player cell as:
#   "J. Gibbs  RB  DET  Jahmyr Gibbs  RB  DET"
# i.e. an abbreviated name then the full name, each followed by pos and team.
PLAYER_CELL = re.compile(r"\s{2,}")


def parse_player_cell(cell: str) -> tuple[str, str, str]:
    """Split a CBS player cell into (full name, position, team)."""
    parts = [p.strip() for p in PLAYER_CELL.split(str(cell).strip()) if p.strip()]
    if len(parts) >= 3:
        # The full name is the third-from-last field; pos and team trail it.
        return parts[-3], parts[-2], parts[-1]
    return str(cell).strip(), "", ""


def flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """CBS uses a two-row header; keep the lower (abbreviated) level."""
    df = df.copy()
    df.columns = [
        c[1].strip() if isinstance(c, tuple) else str(c).strip() for c in df.columns
    ]
    return df


def shorten(col: str) -> str:
    """'yds  Passing Yards' -> 'yds'; disambiguation happens via dedupe()."""
    return PLAYER_CELL.split(col)[0].strip()


def dedupe(names: list[str]) -> list[str]:
    """CBS reuses 'att'/'yds'/'td' for passing and rushing; suffix repeats."""
    seen: dict[str, int] = {}
    out = []
    for n in names:
        if n in seen:
            seen[n] += 1
            out.append(f"{n}.{seen[n]}")
        else:
            seen[n] = 0
            out.append(n)
    return out


def to_league_points(
    points: pd.Series,
    receptions: pd.Series,
    reception_points: float,
    source_reception_points: float = SOURCE_RECEPTION_POINTS,
) -> pd.Series:
    """Restate PPR points under the league's per-reception value.

    Only the reception term differs between scoring formats, so rather than
    recomputing fantasy points from the stat line — which would have to
    reproduce CBS's bonuses and rounding exactly — we adjust that one term
    and leave the rest of their projection untouched.
    """
    delta = source_reception_points - reception_points
    return points - delta * receptions.fillna(0)


def fetch_position(pos: str, season: int) -> pd.DataFrame:
    url = URL_TEMPLATE.format(pos=pos, season=season)
    html = requests.get(url, headers=HEADERS, timeout=30).text
    tables = pd.read_html(io.StringIO(html))
    if not tables:
        raise RuntimeError(f"No tables found at {url}")

    df = flatten_columns(tables[0])

    points_col = next((c for c in df.columns if shorten(c) == "fpts"), None)
    if points_col is None:
        raise RuntimeError(
            f"{pos} {season}: no 'fpts' column found — CBS may have changed "
            f"their table layout. Columns: {df.columns.tolist()}"
        )

    parsed = df.iloc[:, 0].apply(parse_player_cell)
    stats = df.iloc[:, 1:]
    stats.columns = dedupe([shorten(c) for c in stats.columns])

    ppr_points = pd.to_numeric(df[points_col], errors="coerce")
    # QB sheets carry no reception column; nothing to convert there.
    receptions = (
        pd.to_numeric(stats["rec"], errors="coerce")
        if "rec" in stats.columns
        else pd.Series(0.0, index=stats.index)
    )

    out = pd.DataFrame(
        {
            "Player": [p[0] for p in parsed],
            "Team": [p[2] for p in parsed],
            "Position": pos,
            # The draft assistant ranks on AVG. CBS gives a single projection
            # rather than the LOW/AVG/HIGH band the old BeerSheets exports had.
            "AVG": to_league_points(
                ppr_points, receptions, LEAGUE.reception_points
            ),
            "PPR": ppr_points,
        }
    ).join(stats)

    out = out.dropna(subset=["AVG"])
    out = out[out["Player"].astype(str).str.strip() != ""]
    return out.sort_values("AVG", ascending=False).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=SEASON)
    args = parser.parse_args()

    out_dir = data_dir(args.season)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Cache responses so repeated runs during a draft don't re-hit CBS.
    requests_cache.install_cache(str(out_dir / "cbs_cache"), expire_after=3600)

    print(
        f"Scoring: {LEAGUE.scoring_type} "
        f"({LEAGUE.reception_points} pts/reception; CBS source is "
        f"{SOURCE_RECEPTION_POINTS})"
    )
    for pos in POSITIONS:
        df = fetch_position(pos, args.season)
        dest = position_file(pos, args.season)
        df.to_csv(dest, index=False)
        print(f"{pos}: {len(df):>3} players -> {dest.relative_to(out_dir.parent.parent)}")


if __name__ == "__main__":
    main()
