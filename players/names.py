"""Normalise player names and teams so sources can be joined.

Sources disagree constantly: "Marvin Harrison Jr." vs "Marvin Harrison",
"Ken Walker III" vs "Kenneth Walker", JAC vs JAX, WAS vs WSH. Merging on raw
names silently drops players, so everything is keyed on a normalised form.
"""
from __future__ import annotations

import re
import unicodedata

# Generational suffixes carry no identifying information and are applied
# inconsistently across sources.
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

# Team abbreviations that differ between providers, mapped to one spelling.
TEAM_ALIASES = {
    "JAC": "JAX",
    "WAS": "WSH",
    "LA": "LAR",
    "STL": "LAR",
    "SD": "LAC",
    "OAK": "LV",
    "LVR": "LV",
    "ARZ": "ARI",
    "BLT": "BAL",
    "CLV": "CLE",
    "HST": "HOU",
    "SFO": "SF",
    "TAM": "TB",
    "NWE": "NE",
    "NOR": "NO",
    "GNB": "GB",
    "KAN": "KC",
}

# Players whose common names differ beyond what normalisation can bridge.
NAME_ALIASES = {
    "kenneth walker": "ken walker",
    "kenneth gainwell": "kenny gainwell",
    "gabriel davis": "gabe davis",
    "joshua palmer": "josh palmer",
    "cameron ward": "cam ward",
    "christopher rodriguez": "chris rodriguez",
    "nathaniel dell": "tank dell",
    "michael penix": "mike penix",
    "hollywood brown": "marquise brown",
    "chigoziem okonkwo": "chig okonkwo",
    "deebo samuel": "deebo samuel",
}

_PUNCT = re.compile(r"[^a-z0-9 ]")
_SPACES = re.compile(r"\s+")


def normalize_team(team: str | None) -> str:
    """Canonical team abbreviation, uppercased."""
    if not team:
        return ""
    t = str(team).strip().upper()
    return TEAM_ALIASES.get(t, t)


def normalize_name(name: str | None) -> str:
    """Reduce a player name to a form comparable across sources.

    Strips accents, punctuation, case and generational suffixes, then
    applies a small alias table for names that still disagree.
    """
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _PUNCT.sub(" ", text.lower())
    parts = [p for p in _SPACES.split(text) if p and p not in SUFFIXES]
    # Punctuation stripping turns "D.J." into two tokens while ESPN writes
    # "DJ" as one, so the two spellings of the same player never matched and
    # he stayed on the board after being drafted. Rejoin runs of single
    # letters: "d j moore" and "dj moore" both become "dj moore".
    joined, run = [], []
    for part in parts:
        if len(part) == 1:
            run.append(part)
            continue
        if run:
            joined.append("".join(run))
            run = []
        joined.append(part)
    if run:
        joined.append("".join(run))
    cleaned = " ".join(joined)
    return NAME_ALIASES.get(cleaned, cleaned)


def fallback_key(name: str | None, position: str | None, team: str | None) -> str:
    """Looser key used only to reconcile nickname spellings.

    Collapses the first name to its initial, so "Christopher Brooks" and
    "Chris Brooks" agree. Team is required here precisely because the key is
    weak: two players sharing a position, last name and initial on the same
    team is vanishingly rare, whereas across the league it is not.
    """
    normalized = normalize_name(name)
    if not normalized:
        return ""
    parts = normalized.split()
    if len(parts) < 2:
        return ""
    initial, last = parts[0][:1], parts[-1]
    return f"{initial}|{last}|{str(position or '').upper()}|{normalize_team(team)}"


def player_key(name: str | None, position: str | None) -> str:
    """Join key for a player.

    Position is included because normalised names are not unique on their
    own — but team deliberately is not, since players change teams and
    sources update rosters at different times.
    """
    return f"{normalize_name(name)}|{str(position or '').strip().upper()}"
