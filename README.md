# fantasy-draft-assistant

A local, terminal-driven fantasy football draft assistant. It ranks players by
**VOR (value over replacement)** with flex-aware replacement levels, then walks
you pick-by-pick through a snake draft, suggesting the player who adds the most
to your projected starting lineup.

Used for the 2025 draft.

## League settings

Configured at the top of `chat_gpt_draft_assistant.py`:

| Setting | Value |
| --- | --- |
| League size | 12 teams |
| Draft slot | 12 |
| Starters | QB 1, RB 2, WR 2, TE 1, FLEX 2 |
| Flex eligible | RB / WR / TE |
| Bench | 5 |
| Projection column | `AVG` |

## Scripts

| Script | What it does |
| --- | --- |
| `chat_gpt_draft_assistant.py` | The main tool. Interactive snake-draft assistant — tracks every team's picks, recomputes suggestions each pick, prints your final starters + bench. |
| `chat_gpt_fantasy_rankings.py` | Standalone flex-aware VOR rankings; writes `DraftSheets Fantasy Tool/rankings_vor_flexaware.csv`. |
| `combine_data_beersheets.py` | Merges the per-position sheets into `FULL-Table 1.csv`, adding an `AVG Differential` column (points above the average league starter at that position). |
| `download_data_scraper.py` | Scrapes CBS PPR season projections into `cbs_stats.csv` (uses `requests_cache`). |
| `download_data_nfl_data.py` | Scratch script — dumps `nfl_data_py` seasonal data. |

### How the assistant ranks

1. Compute the replacement-level player at each position for a 12-team league.
2. Greedily allocate the 24 league-wide FLEX slots to the next-best RB/WR/TE,
   pushing those replacement levels deeper.
3. `VOR = AVG − ReplacementAVG`.
4. Each pick, score candidates by **marginal gain**: how much your best legal
   starting lineup improves if you add that player, measured against a
   "ghost" roster of replacement-level players.

## Data (not committed)

Data files are gitignored. To run, recreate this layout in the repo root:

```
DraftSheets Fantasy Tool/
  QB-Table 1.csv
  RB-Table 1.csv
  WR-Table 1.csv
  TE-Table 1.csv
  ...
```

Each per-position CSV needs at minimum a `Player` column and an `AVG` column
(projected points). These were manual exports from a BeerSheets / FantasyPros
ECR spreadsheet — **no script in this repo regenerates them**; only
`cbs_stats.csv` is scraped. Drop in fresh sheets each season.

The other CSVs in that folder (ECR, RISK, SNAKE, Rookies, Scoring, AUC,
Aggregate, FLEX EST) were reference tabs from the same workbook and are not
read by these scripts.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
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
