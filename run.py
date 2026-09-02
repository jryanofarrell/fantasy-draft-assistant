#!/usr/bin/env python3
"""Entry point for every tool in this repo.

    ./run.py draft                    # interactive draft assistant
    ./run.py rankings                 # write flex-aware VOR rankings
    ./run.py projections --season 2026
    ./run.py combine
    ./run.py league                   # print the active league config
    ./run.py espn --write             # diff league.yaml against ESPN

Running from the repo root puts it on sys.path, so every module can use
absolute imports (`from league.config import ...`) with no path shims.
Arguments after the command are passed straight through.
"""
import runpy
import sys

COMMANDS = {
    "draft": ("draft.draft_assistant", "Interactive snake-draft assistant"),
    "rankings": ("draft.fantasy_rankings", "Write flex-aware VOR rankings"),
    "projections": ("data_scripts.download_projections", "Download CBS projections"),
    "combine": ("data_scripts.combine_data", "Merge sheets into FULL-Table"),
    "league": ("league.league", "Print the active league config"),
    "espn": ("league.import_espn_league", "Diff league.yaml against ESPN"),
}


def usage() -> None:
    print(__doc__.strip().splitlines()[0])
    print("\nusage: ./run.py <command> [args...]\n")
    width = max(len(c) for c in COMMANDS)
    for name, (_, help_text) in COMMANDS.items():
        print(f"  {name.ljust(width)}  {help_text}")
    print("\nAny further arguments are passed to the command, e.g."
          "\n  ./run.py projections --season 2026")


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help", "help"}:
        usage()
        return 0

    command = sys.argv[1]
    if command not in COMMANDS:
        print(f"error: unknown command {command!r}\n", file=sys.stderr)
        usage()
        return 2

    module, _ = COMMANDS[command]
    # Hand the command its own argv so argparse in the target module sees
    # `./run.py projections --season 2026` as `projections --season 2026`.
    sys.argv = [f"{sys.argv[0]} {command}"] + sys.argv[2:]
    runpy.run_module(module, run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
