import pandas as pd
import requests
import requests_cache

BASE = "https://www.cbssports.com/fantasy/football/stats/QB/2025/season/projections/ppr/"

# cache requests to be polite and faster during dev
requests_cache.install_cache("cbs_stats_cache", expire_after=3600)

def fetch_tables(url: str) -> list[pd.DataFrame]:
    # send a realistic UA to avoid basic bot blocks
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/537.36"}
    html = requests.get(url, headers=headers, timeout=30).text
    # read_html returns a list of DataFrames found on the page
    return pd.read_html(html)

# Example: overall player stats page (adjust path to passers/rushers/receivers, season, week, etc.)
url = BASE  # e.g. 'https://www.cbssports.com/fantasy/football/stats/players/2024/all/ppr/'
tables = fetch_tables(url)

print(f"Found {len(tables)} tables")
for i, df in enumerate(tables, 1):
    print(f"\nTable {i} shape: {df.shape}")
    print(df.head())

# If you identify the main stats table, clean & save:
if tables:
    stats = tables[0]
    # print("columns", stats.columns)
    # light cleanup
    stats.columns = [c[1].strip() for c in stats.columns]
    stats.to_csv("cbs_stats.csv", index=False)
