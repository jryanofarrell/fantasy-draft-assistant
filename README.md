# fantasy-draft-assistant

A local, terminal-driven fantasy football draft assistant. It ranks players by
**VOR (value over replacement)** with flex-aware replacement levels, then walks
you pick-by-pick through a snake draft, suggesting the player who adds the most
to your projected starting lineup.

Used for the 2025 draft; refreshed with CBS projections for 2026.

## League settings

All league settings live in **`league.yaml`**, which mirrors what you can
change in ESPN (League Settings → Basic / Roster / Scoring). Edit that file
rather than the scripts.

| Setting | Value |
| --- | --- |
| League | Le Ligue (ESPN 1280742) |
| Season | 2026 |
| League size | 12 teams |
| Draft slot | 4 |
| Scoring | half PPR (0.5 pts/reception, converted on download) |
| Starters | QB 1, RB 2, WR 2, TE 1, FLEX 2, D/ST 1, K 1 |
| Flex eligible | RB / WR / TE |
| Bench | 4 (+1 IR) |

Settings were imported from ESPN and verified — `import_espn_league.py`
currently reports no differences.

Print the loaded config at any time:

```bash
./run.py league
```

The loader validates on load and refuses to run on a config that would
silently produce a wrong draft board — a `scoring_type` that disagrees with
the per-reception value, a draft slot outside the league, a FLEX slot with no
eligible positions, and so on.

### Importing from ESPN

Rather than hand-checking settings, pull them from the league directly:

```bash
cp auth.example auth      # then fill in your cookies
./run.py espn
```

The script prints ESPN's settings beside the current `league.yaml` and marks
every field that differs. It does not modify `league.yaml`; `--write` saves the
ESPN values to `league.espn.yaml` for you to review and merge.

`auth` holds your league id, team id, and ESPN cookies. It is gitignored;
`auth.example` is the committed template. Values can also come from the
environment or `--league-id` / `--espn-s2` / `--swid` flags, which take
precedence over the file.

**Getting the cookies.** ESPN has no username/password API — its login is
reCAPTCHA-gated — so a private league needs two cookies from a logged-in
browser session. DevTools → Application → Cookies → `https://www.espn.com`,
then copy `espn_s2` (long string) and `SWID` (a GUID in braces). `espn_s2`
lasts about a year, so this is a one-time setup per season. Public leagues
need no cookies at all.

These are live session credentials for your whole ESPN/Disney account, not
just fantasy. Keep them in `auth`, and don't paste them into chats or issues.

Scoring rules ESPN reports that aren't modelled in `league.yaml` are listed
rather than silently dropped, so you can see what wasn't carried across.

### Kickers and defenses

`league.yaml` records K and D/ST slots and their scoring so the file is a
complete picture of the league, but the assistant does not rank them — there
are no projections for those positions in the data. If you set those slots to
a non-zero count, the tool excludes them from its roster math and you draft
them yourself.

## Layout

```
run.py                 entry point for everything
config.py              league settings + data paths, shared by all scripts
league/                what the league's rules are
  league.yaml            the settings (edit this)
  league.py              loads and validates them
  import_espn_league.py  pulls live settings from ESPN
players/               getting player projections
  sources/               one adapter per provider (cbs, sleeper, espn)
  names.py               name/team normalisation for cross-source matching
  consensus.py           merges sources into one board
  download_projections.py  orchestrates fetch -> per-source -> consensus
  combine_data.py          merge sheets into FULL-Table
draft/                 drafting tools
  draft_assistant.py     interactive snake-draft assistant
  fantasy_rankings.py    standalone VOR rankings
data/<season>/<scoring>/   projection sheets (gitignored)
auth                   ESPN credentials (gitignored)
```

Everything runs through `run.py`, which puts the repo root on `sys.path` so
modules can use absolute imports (`from config import ...`) without
path shims. Running the scripts directly will not work.

`run.py` re-execs itself under `.venv` if started outside it, so `./run.py`
works without activating anything. Set `FFDRAFT_NO_REEXEC=1` to suppress
that and use whatever interpreter you invoked it with.

## Commands

| Command | What it does |
| --- | --- |
| `./run.py projections --season 2026` | Scrapes CBS projections into `data/<season>/`. Run first each season. |
| `./run.py draft` | The main tool. Interactive snake-draft assistant — tracks every team's picks, recomputes suggestions each pick, prints your final starters + bench. |
| `./run.py rankings` | Writes `data/<season>/rankings_vor_flexaware.csv`. |
| `./run.py combine` | Merges the per-position sheets into `FULL-Table 1.csv` with an `AVG Differential` column. |
| `./run.py league` | Prints the active league config. |
| `./run.py espn` | Diffs `league.yaml` against live ESPN settings. `--write` saves them to `league/league.espn.yaml`. |

Run `./run.py` with no arguments for the command list.

### How the assistant ranks

1. Compute the replacement-level player at each position for a 12-team league.
2. Greedily allocate the 24 league-wide FLEX slots to the next-best RB/WR/TE,
   pushing those replacement levels deeper.
3. `VOR = AVG − ReplacementAVG`.
4. Each pick, score candidates by **marginal gain**: how much your best legal
   starting lineup improves if you add that player, measured against a
   "ghost" roster of replacement-level players.

## Data (not committed)

Data is gitignored and organised by season and scoring format:

```
data/2026/
  half_ppr/
    QB-Table 1.csv          <- consensus; the draft tools read this
    RB-Table 1.csv  ...
    sources/
      cbs/QB-Table 1.csv    <- each source as downloaded
      sleeper/QB-Table 1.csv
      espn/QB-Table 1.csv
  ppr/        ...same shape
  standard/   ...same shape
```

Rebuild with `./run.py projections`, which writes the league's format by
default, or `--all-scorings` for all three.

### Sources

| Source | Auth | Depth | Formats | Notes |
| --- | --- | --- | --- | --- |
| `cbs` | none | ~100/pos | all three | Full stat lines. Only PPR and non-PPR pages exist, and they disagree by more than receptions, so PPR is treated as truth and the others derived from it. |
| `sleeper` | none | ~550 | all three | The only source publishing every format natively. Carries injury status. |
| `espn` | `auth` | ~400 | league only | Scored server-side under your league's exact rules, so it needs no conversion — and for the same reason exists only for the format you play. |

### Consensus

Sources disagree substantially — often 15% on the same player, and far more
on backup quarterbacks where playing time is contested. The board takes the
**median** across sources rather than the mean, so one stale injury
assumption can't drag a player tens of points.

Every row records `sources` (how many contributed) and `spread` (max minus
min), plus each source's own number in an `AVG_<source>` column. A projection
resting on a single opinion is visible rather than implied.

Names are normalised before merging — accents, punctuation, case and
generational suffixes are stripped, and team abbreviations are canonicalised
(JAC/JAX, WAS/WSH). Spellings that still disagree, like "Chris" versus
"Christopher", are reconciled on a looser key of first initial + last name +
position + team. As of the last run, every one of the top 150 players matched
across all three sources.

### Scoring conversion

Where a source doesn't publish a format natively, it is derived by adjusting
the reception term only:

```
points = PPR_points − (1.0 − reception_points) × receptions
```

The rest of the source's projection is left untouched, rather than recomputing
from the stat line and having to reproduce each provider's bonuses and
rounding. Quarterbacks have no reception column and pass through unchanged.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./run.py projections --season 2026
```

`prompt_toolkit` is optional — install it for fuzzy player-name autocomplete
during the draft. Without it the tool falls back to plain `input()` and you
must type names exactly as `Name (POS)`.

## Running a draft

```bash
./run.py draft
```

At each pick:

- **Your pick** — press Enter to take the top suggestion, or type `Name (POS)`.
- **Another team's pick** — type what they took, or `auto` / Enter to assume
  they took the best available by VOR.
- `quit` / `exit` to stop early.

It ends after 13 roster spots (8 starters + 5 bench) and prints your final
starters and bench.
