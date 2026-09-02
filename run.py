#!/usr/bin/env python3
"""Entry point for every tool in this repo.

    ./run.py draft                    # interactive draft assistant
    ./run.py rankings                 # write flex-aware VOR rankings
    ./run.py projections --season 2026
    ./run.py combine
    ./run.py league                   # print the active league config
    ./run.py espn --write             # diff league.yaml against ESPN

Running from the repo root puts it on sys.path, so every module can use
absolute imports (`from config import ...`) with no path shims.
Arguments after the command are passed straight through.
"""
import os
import runpy
import sys
from pathlib import Path

VENV_DIR = Path(__file__).resolve().parent / ".venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"


def reexec_in_venv() -> None:
    """Re-run under the repo virtualenv if we were started outside it.

    The shebang resolves to whatever python3 is on PATH, which generally
    lacks this repo's dependencies. Re-execing means `./run.py` works
    without anyone having to remember to activate anything.
    """
    if os.environ.get("FFDRAFT_NO_REEXEC"):
        return
    if not VENV_PYTHON.exists():
        return
    # Compare sys.prefix, not the interpreter path: .venv/bin/python is a
    # symlink to the system binary, so resolving it makes the two look equal.
    if Path(sys.prefix) == VENV_DIR:
        return
    os.environ["FFDRAFT_NO_REEXEC"] = "1"
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])


COMMANDS = {
    "draft": ("draft.draft_assistant", "Interactive snake-draft assistant"),
    "rankings": ("draft.fantasy_rankings", "Write flex-aware VOR rankings"),
    "projections": ("players.download_projections", "Download CBS projections"),
    "combine": ("players.combine_data", "Merge sheets into FULL-Table"),
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
    reexec_in_venv()

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
