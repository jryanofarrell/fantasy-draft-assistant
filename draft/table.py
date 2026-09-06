"""Box-drawn tables for the terminal.

pandas' to_string is fine for a notebook and poor on a draft clock: columns
drift as values change width and rows run together. Borders keep the eye on
the right line when the board is redrawn every pick.
"""
from __future__ import annotations

import pandas as pd

# Light box-drawing characters, in terminal order.
TL, TR, BL, BR = "┌", "┐", "└", "┘"
H, V = "─", "│"
T_DOWN, T_UP, T_LEFT, T_RIGHT, CROSS = "┬", "┴", "├", "┤", "┼"


def _decimals(values) -> int:
    """Decimals a column needs: the fewest that still represent every value.

    Chosen per column rather than per cell, so a column doesn't come out
    ragged with 281.8 sitting beside 314.91, and a value already rounded to
    one decimal upstream doesn't gain a fake second one.
    """
    needed = 0
    for v in values:
        if not isinstance(v, float) or pd.isna(v):
            continue
        for places in range(3):
            if abs(round(v, places) - v) < 1e-9:
                needed = max(needed, places)
                break
        else:
            needed = 2
    return needed


def _fmt(value, decimals: int = 2) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, float):
        return f"{value:.{decimals}f}"
    return str(value)


def render(df: pd.DataFrame, index_name: str | None = None) -> str:
    """A bordered table. Numeric columns right-align, text left-aligns."""
    if df.empty:
        return ""

    columns = list(df.columns)
    places = [_decimals(df[c]) if pd.api.types.is_float_dtype(df[c]) else 2
              for c in columns]
    cells = [[_fmt(v, places[i]) for i, v in enumerate(row)]
             for row in df.itertuples(index=False)]

    if index_name is not None:
        columns = [index_name] + columns
        cells = [[str(i)] + row for i, row in zip(df.index, cells)]

    numeric = [
        all(c == "" or c.replace("-", "").replace(".", "").isdigit() for c in col)
        for col in zip(*cells)
    ] if cells else [False] * len(columns)

    widths = [
        max(len(str(columns[i])), *(len(row[i]) for row in cells))
        for i in range(len(columns))
    ]

    def line(left, mid, right):
        return left + mid.join(H * (w + 2) for w in widths) + right

    def row(values):
        out = []
        for i, value in enumerate(values):
            out.append(f" {value:>{widths[i]}} " if numeric[i]
                       else f" {value:<{widths[i]}} ")
        return V + V.join(out) + V

    lines = [line(TL, T_DOWN, TR),
             V + V.join(f" {str(c):>{widths[i]}} " if numeric[i]
                        else f" {str(c):<{widths[i]}} "
                        for i, c in enumerate(columns)) + V,
             line(T_LEFT, CROSS, T_RIGHT)]
    lines += [row(r) for r in cells]
    lines.append(line(BL, T_UP, BR))
    return "\n".join(lines)
