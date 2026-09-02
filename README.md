# fantasy-draft-assistant

A local, terminal-driven fantasy football draft assistant. It ranks players by
**VOR (value over replacement)** with flex-aware replacement levels, then walks
you pick-by-pick through a snake draft, suggesting the player who adds the most
to your projected starting lineup.

Used for the 2025 draft; refreshed with CBS projections for 2026.

## League settings

Configured in `config.py`:

| Setting | Value |
| --- | --- |
| League size | 12 teams |
| Draft slot | 12 |
| Starters | QB 1, RB 2, WR 2, TE 1, FLEX 2 |
| Flex eligible | RB / WR / TE |
| Bench | 5 |
| Projection column | `AVG` |
| Season | 2026 |

## Scripts

| Script | What it does |
| --- | --- |
| `download_projections.py` | Scrapes CBS PPR season projections for QB/RB/WR/TE into `data/<season>/<POS>-Table 1.csv`. Run this first each season. |
| `chat_gpt_draft_assistant.py` | The main tool. Interactive snake-draft assistant — tracks every team's picks, recomputes suggestions each pick, prints your final starters + bench. |
| `chat_gpt_fantasy_rankings.py` | Standalone flex-aware VOR rankings; writes `data/<season>/rankings_vor_flexaware.csv`. |
| `combine_data_beersheets.py` | Merges the per-position sheets into `FULL-Table 1.csv`, adding an `AVG Differential` column (points above the average league starter at that position). |
| `download_data_nfl_data.py` | Scratch script — dumps `nfl_data_py` seasonal data. |
| `config.py` | Season, league settings, and data paths shared by all of the above. |

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
