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
| Season | 2026 |
| League size | 12 teams |
| Draft slot | 12 |
| Scoring | half PPR (0.5 pts/reception, converted on download) |
| Starters | QB 1, RB 2, WR 2, TE 1, FLEX 2 |
| Flex eligible | RB / WR / TE |
| Bench | 5 |

Print the loaded config at any time:

```bash
python league.py
```

The loader validates on load and refuses to run on a config that would
silently produce a wrong draft board — a `scoring_type` that disagrees with
the per-reception value, a draft slot outside the league, a FLEX slot with no
eligible positions, and so on.

> ⚠️ **Verify against ESPN before drafting.** Fields in `league.yaml` marked
> `[carried over]` came from last season's hardcoded script; `[ESPN default]`
> fields are guesses. In particular ESPN defaults to FLEX 1, a K and a D/ST
> slot, and a 7-man bench — this config carries last year's FLEX 2, no K or
> D/ST, and a 5-man bench.

### Importing from ESPN

Rather than hand-checking the settings, pull them from the league directly:

```bash
export ESPN_S2='...' ESPN_SWID='{...}'      # private leagues only
python import_espn_league.py --league-id 123456
```

`--league-id` is the `leagueId` in your ESPN URL. The script prints ESPN's
settings beside the current `league.yaml` and marks every field that differs.
It does not modify `league.yaml`; `--write` saves the ESPN values to
`league.espn.yaml` for you to review and merge.

Private leagues need the `espn_s2` and `SWID` cookies from a logged-in browser
session (DevTools → Application → Cookies → espn.com). Prefer the environment
variables over `--espn-s2` / `--swid` flags so the cookies don't land in your
shell history. They are credentials — don't commit them.

Scoring rules ESPN reports that aren't modelled in `league.yaml` are listed
rather than silently dropped, so you can see what wasn't carried across.

### Kickers and defenses

`league.yaml` records K and D/ST slots and their scoring so the file is a
complete picture of the league, but the assistant does not rank them — there
are no projections for those positions in the data. If you set those slots to
a non-zero count, the tool excludes them from its roster math and you draft
them yourself.

## Scripts

| Script | What it does |
| --- | --- |
| `download_projections.py` | Scrapes CBS PPR season projections for QB/RB/WR/TE into `data/<season>/<POS>-Table 1.csv`. Run this first each season. |
| `chat_gpt_draft_assistant.py` | The main tool. Interactive snake-draft assistant — tracks every team's picks, recomputes suggestions each pick, prints your final starters + bench. |
| `chat_gpt_fantasy_rankings.py` | Standalone flex-aware VOR rankings; writes `data/<season>/rankings_vor_flexaware.csv`. |
| `combine_data_beersheets.py` | Merges the per-position sheets into `FULL-Table 1.csv`, adding an `AVG Differential` column (points above the average league starter at that position). |
| `download_data_nfl_data.py` | Scratch script — dumps `nfl_data_py` seasonal data. |
| `league.py` | Loads and validates `league.yaml`. Run directly to print the active league. |
| `import_espn_league.py` | Pulls live settings from ESPN and diffs them against `league.yaml`. |
| `config.py` | Bridges `league.yaml` to the scripts and resolves data paths. |

### How the assistant ranks

1. Compute the replacement-level player at each position for a 12-team league.
2. Greedily allocate the 24 league-wide FLEX slots to the next-best RB/WR/TE,
   pushing those replacement levels deeper.
3. `VOR = AVG − ReplacementAVG`.
4. Each pick, score candidates by **marginal gain**: how much your best legal
   starting lineup improves if you add that player, measured against a
   "ghost" roster of replacement-level players.

## Data (not committed)

Data lives under `data/<season>/` and is gitignored. Regenerate it with:

```bash
python download_projections.py --season 2026
```

That writes one sheet per position:

```
data/2026/
  QB-Table 1.csv
  RB-Table 1.csv
  WR-Table 1.csv
  TE-Table 1.csv
```

Each sheet carries `Player`, `Team`, `Position`, `AVG` (CBS projected season
PPR points) and the underlying stat columns. `AVG` is what every downstream
script ranks on.

### Scoring conversion

CBS publishes `ppr` and `nonppr` pages but no half-PPR, so `AVG` is converted
on download to the league's per-reception value from `league.yaml`:

```
AVG = CBS_PPR_points − (1.0 − reception_points) × receptions
```

Only the reception term differs between scoring formats, so this adjusts that
one term and leaves the rest of CBS's projection alone — rather than
recomputing points from the stat line, which would have to reproduce their
bonuses and rounding exactly. Each sheet keeps the unmodified CBS number in a
`PPR` column next to the converted `AVG`, so the conversion is auditable.

This needs only a reception count, not a full stat line — both CBS (`rec`)
and the older BeerSheets exports (`REC`) carry one. Quarterback sheets have no
reception column and are passed through unchanged.

> CBS's own `ppr` and `nonppr` pages differ by more than receptions (Jahmyr
> Gibbs by 16.5 points), so they are not internally consistent. This
> conversion treats the PPR projection as the source of truth and assumes
> half PPR differs from it only in the per-reception value.

### Source note

Through 2025 the sheets were manual exports from a BeerSheets / FantasyPros
ECR workbook, which supplied a `LOW` / `AVG` / `HIGH` projection band plus
extra reference tabs (RISK, SNAKE, Rookies, Scoring, ECR). Those exports are
preserved under `data/2025/` locally but are not reproducible from code.

From 2026 the sheets come from CBS via `download_projections.py`, which gives
a single point projection rather than a band. Nothing in the repo consumed
`LOW`/`HIGH`, so ranking behaviour is unchanged — but the uncertainty
information is gone, and there is no rookie or bye-week data.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python download_projections.py --season 2026
```

`prompt_toolkit` is optional — install it for fuzzy player-name autocomplete
during the draft. Without it the tool falls back to plain `input()` and you
must type names exactly as `Name (POS)`.

## Running a draft

```bash
python chat_gpt_draft_assistant.py
```

At each pick:

- **Your pick** — press Enter to take the top suggestion, or type `Name (POS)`.
- **Another team's pick** — type what they took, or `auto` / Enter to assume
  they took the best available by VOR.
- `quit` / `exit` to stop early.

It ends after 13 roster spots (8 starters + 5 bench) and prints your final
starters and bench.
