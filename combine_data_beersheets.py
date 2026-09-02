
import pandas as pd

position_numbers = {
    "QB": 12,
    "RB": 36,
    "WR": 36,
    "TE": 12
}
path = "./DraftSheets Fantasy Tool"
all_frames = []

for position, starter_count in position_numbers.items():
    file_path = f"{path}/{position}-Table 1.csv"
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

result_overall.to_csv(f"{path}/FULL-Table 1.csv", index=False)
