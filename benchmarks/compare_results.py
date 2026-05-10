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
THRESHOLD = 0.10


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
    if has_prev:
        df["abs_pct"] = df[["abs_pct", "pct_prev"]].abs().max(axis=1).fillna(0)
    df = df.sort_values("abs_pct", ascending=False)
    significant = df[df["abs_pct"] > THRESHOLD]
    skipped = len(df) - len(significant)

    base_col = f"time @ {args.baseline_label}"
    head_col = "time @ head"
    delta_col = "Δ vs base"
    prev_delta = f"Δ vs {args.prev_label}" if has_prev else None

    def render_row(r):
        row = {
            "configuration": r["configuration"],
            "workload": r["workload"],
            "function": r["function"],
            base_col: format_time(r["t_base"]) if pd.notna(r["t_base"]) else "",
            head_col: format_time(r["t_head"]) if pd.notna(r["t_head"]) else "",
            delta_col: flag(r["pct_base"]),
        }
        if has_prev:
            row[prev_delta] = flag(r.get("pct_prev"))
        return row

    summary = f"Significant changes (|Δ| > {int(THRESHOLD * 100)}%): {len(significant)}"
    if skipped:
        summary += f" — {skipped} other rows hidden"
    print(f"<details><summary>{summary}</summary>\n")

    if not len(significant):
        print("_no significant changes_")
    else:
        for topic, topic_df in significant.groupby("topic", sort=False):
            print(f"\n#### {topic}\n")
            cols = ["configuration", "workload", "function",
                    base_col, head_col, delta_col]
            if has_prev:
                cols.append(prev_delta)
            # Drop columns that carry no information within this topic.
            constant = [c for c in ("configuration", "workload")
                        if topic_df[c].nunique() <= 1
                        and (topic_df[c] == "").all()]
            cols = [c for c in cols if c not in constant]
            out = pd.DataFrame([render_row(r) for _, r in topic_df.iterrows()])
            print(out[cols].to_markdown(index=False))
    print("\n</details>")


if __name__ == "__main__":
    main()
