"""Download projections from every source and build the consensus board.

    ./run.py projections                       # league scoring, all sources
    ./run.py projections --scoring ppr
    ./run.py projections --all-scorings
    ./run.py projections --sources cbs,sleeper

Per-source sheets land in data/<season>/<scoring>/sources/<source>/ and the
merged board the draft tools read is written alongside them at
data/<season>/<scoring>/<POS>-Table 1.csv.
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from config import POSITIONS, SCORING, SCORING_FORMATS, SEASON, position_file, scoring_dir
from players import consensus
from players.sources import SOURCES


def write_frame(df: pd.DataFrame, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def run(season: int, scorings: list[str], sources: list[str], min_sources: int) -> int:
    fetched: dict[str, dict[str, pd.DataFrame]] = {}
    for name in sources:
        module = SOURCES[name]
        try:
            fetched[name] = module.fetch(season)
        except Exception as exc:  # a dead source shouldn't sink the others
            print(f"  {name}: FAILED — {exc}", file=sys.stderr)
            fetched[name] = {}
        else:
            formats = ", ".join(sorted(fetched[name])) or "nothing"
            rows = sum(len(d) for d in fetched[name].values())
            print(f"  {name}: {rows} rows across {formats}")

    if not any(fetched.values()):
        print("error: every source failed", file=sys.stderr)
        return 1

    for scoring in scorings:
        by_source = {
            name: frames[scoring]
            for name, frames in fetched.items()
            if scoring in frames and not frames[scoring].empty
        }
        if not by_source:
            print(f"\n{scoring}: no source produced this format, skipping")
            continue

        for name, df in by_source.items():
            for pos in POSITIONS:
                subset = df[df["Position"] == pos]
                if not subset.empty:
                    write_frame(subset, position_file(pos, season, scoring, source=name))

        board = consensus.build(by_source, min_sources=min_sources)
        print(f"\n{scoring}  ({', '.join(sorted(by_source))})")
        for pos in POSITIONS:
            subset = board[board["Position"] == pos].reset_index(drop=True)
            write_frame(subset, position_file(pos, season, scoring))
            full = int((subset["sources"] == len(by_source)).sum())
            print(f"  {pos}: {len(subset):>4} players  ({full} with all "
                  f"{len(by_source)} sources)")
        print(f"  -> {scoring_dir(scoring, season)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, default=SEASON)
    ap.add_argument("--scoring", default=SCORING, choices=SCORING_FORMATS,
                    help=f"scoring format to build (default: {SCORING})")
    ap.add_argument("--all-scorings", action="store_true",
                    help="build every scoring format, not just the league's")
    ap.add_argument("--sources", default=",".join(SOURCES),
                    help=f"comma-separated subset of: {', '.join(SOURCES)}")
    ap.add_argument("--min-sources", type=int, default=1,
                    help="drop players backed by fewer than this many sources")
    args = ap.parse_args()

    requested = [s.strip() for s in args.sources.split(",") if s.strip()]
    unknown = [s for s in requested if s not in SOURCES]
    if unknown:
        print(f"error: unknown source(s) {unknown}; known: {list(SOURCES)}",
              file=sys.stderr)
        return 2

    scorings = list(SCORING_FORMATS) if args.all_scorings else [args.scoring]
    print(f"season {args.season} | scoring: {', '.join(scorings)}\n"
          f"fetching {len(requested)} source(s)")
    return run(args.season, scorings, requested, args.min_sources)


if __name__ == "__main__":
    raise SystemExit(main())
