"""Compare benchmark CSVs and emit a markdown delta table.

Usage:
    compare_results.py --baseline baseline.csv --head head.csv
                       [--prev prev.csv]
                       [--baseline-label SHA] [--prev-label SHA]
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_benchmarks import format_time  # noqa: E402

KEY = ["topic", "configuration", "workload", "function"]
THRESHOLD = 0.05


def load(path):
    if not path or not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return None
    if df.empty or not set(KEY).issubset(df.columns) or "time" not in df.columns:
        return None
    for k in KEY:
        df[k] = df[k].fillna("").astype(str)
    return df[KEY + ["time"]]


def flag(pct):
    if pd.isna(pct):
        return ""
    if pct > THRESHOLD:
        return f"🔴 {pct * 100:+.1f}%"
    if pct < -THRESHOLD:
        return f"🟢 {pct * 100:+.1f}%"
    return f"{pct * 100:+.1f}%"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--prev", default=None)
    p.add_argument("--baseline-label", default="baseline")
    p.add_argument("--prev-label", default="HEAD~")
    args = p.parse_args()

    base = load(args.baseline)
    head = load(args.head)
    if base is None or head is None:
        print("_no baseline available for comparison_")
        return

    base = base.rename(columns={"time": "t_base"})
    head = head.rename(columns={"time": "t_head"})
    df = base.merge(head, on=KEY, how="outer")
    df["pct_base"] = (df["t_head"] - df["t_base"]) / df["t_base"]

    has_prev = False
    if args.prev:
        prev = load(args.prev)
        if prev is not None:
            prev = prev.rename(columns={"time": "t_prev"})
            df = df.merge(prev, on=KEY, how="left")
            df["pct_prev"] = (df["t_head"] - df["t_prev"]) / df["t_prev"]
            has_prev = True

    df["abs_pct"] = df["pct_base"].abs().fillna(0)
    df = df.sort_values("abs_pct", ascending=False)

    cols = [
        "topic",
        "configuration",
        "workload",
        "function",
        f"time @ {args.baseline_label}",
        "time @ head",
        "Δ vs base",
    ]
    if has_prev:
        cols.append(f"Δ vs {args.prev_label}")

    rows = []
    for _, r in df.iterrows():
        row = {
            "topic": r["topic"],
            "configuration": r["configuration"],
            "workload": r["workload"],
            "function": r["function"],
            f"time @ {args.baseline_label}": format_time(r["t_base"])
            if pd.notna(r["t_base"]) else "",
            "time @ head": format_time(r["t_head"])
            if pd.notna(r["t_head"]) else "",
            "Δ vs base": flag(r["pct_base"]),
        }
        if has_prev:
            row[f"Δ vs {args.prev_label}"] = flag(r.get("pct_prev"))
        rows.append(row)

    out = pd.DataFrame(rows, columns=cols)
    print(out.to_markdown(index=False))


if __name__ == "__main__":
    main()
