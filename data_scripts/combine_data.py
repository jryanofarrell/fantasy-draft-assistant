
import sys
from pathlib import Path

# This script lives in data_scripts/; the shared config sits at the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from config import SEASON, data_dir, position_file

position_numbers = {
    "QB": 12,
    "RB": 36,
    "WR": 36,
    "TE": 12
}
all_frames = []

for position, starter_count in position_numbers.items():
    file_path = position_file(position, SEASON)
    # Treat common empty tokens as NaN on read
    df = pd.read_csv(file_path, na_values=["NaN", "nan", "", " ", "Â", "Â "], keep_default_na=True)

    # Remove rows where Player is missing
    df = df.dropna(subset=["Player"]).reset_index(drop=True)       # or: df = df[df["Player"].notna()]
    df_starters = df[:starter_count]

    avg = df_starters["AVG"].mean()

    df["AVG Differential"] = df["AVG"] - avg
    df["Position"] = position
    print(position, df.head())
    all_frames.append(df)

result = pd.concat(all_frames, ignore_index=True)
result_overall = result.sort_values("AVG Differential", ascending=False)
print(result.head(10))

result_overall.to_csv(data_dir(SEASON) / "FULL-Table 1.csv", index=False)
