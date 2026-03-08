import subprocess
import json
import sys
import os
import math
from typing import List, Dict

try:
    import pandas as pd
except ImportError:
    pd = None


def run_script(script_path: str) -> List[Dict]:
    print(f"Running {script_path}...", file=sys.stderr)
    try:
        # Run the script and capture stdout
        result = subprocess.run(
            [sys.executable, script_path], capture_output=True, text=True, check=True
        )
        # The scripts print JSON to stdout
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error running {script_path}:", file=sys.stderr)
        print(e.stderr, file=sys.stderr)
        return []
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from {script_path}: {e}", file=sys.stderr)
        print("Output was:", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        return []


def round_to_2_sig_figs(x):
    try:
        x = float(x)
        if x == 0 or not math.isfinite(x):
            return x
        return round(x, 2 - int(math.floor(math.log10(abs(x)))) - 1)
    except (ValueError, TypeError):
        return x


def format_time(seconds: float) -> str:
    if seconds < 1e-6:
        return f"{seconds * 1e9:g} ns"
    elif seconds < 1e-3:
        return f"{seconds * 1e6:g} µs"
    elif seconds < 1:
        return f"{seconds * 1e3:g} ms"
    else:
        return f"{seconds:g} s"


def main():
    benchmark_dir = os.path.dirname(os.path.abspath(__file__))
    scripts = [
        "benchmark_digest.py",
        "benchmark_storage.py",
        "benchmark_integration.py",
    ]

    all_results = []

    for script in scripts:
        results = run_script(os.path.join(benchmark_dir, script))
        all_results.extend(results)

    if not all_results:
        print("No results collected.")
        return

    # Round all time results
    for res in all_results:
        if "time" in res:
            res["time"] = round_to_2_sig_figs(res["time"])

    if pd:
        # Process results into a DataFrame for display
        df = pd.DataFrame(all_results)

        # Select and reorder columns
        display_cols = ["benchmark", "name", "storage", "iterations", "time"]
        # 'storage' column might not exist in all results
        if "storage" not in df.columns:
            df["storage"] = ""
        else:
            df["storage"] = df["storage"].fillna("")

        final_df = df[[c for c in display_cols if c in df.columns]]

        # Sort the dataframe by time before grouping to preserve order (descending: largest value on top)
        df = df.sort_values(by="time", ascending=False)
        final_df = df[[c for c in display_cols if c in df.columns]]

        def add_color_to_cell(
            val_str: str, raw_val: float, min_val: float, max_val: float
        ) -> str:
            # Using 🟢, 🟡, 🔴 emojis as a fallback gradient is safer for Github markdown.

            if max_val == min_val:
                ratio = 0
            else:
                ratio = (raw_val - min_val) / (max_val - min_val)

            if ratio < 0.33:
                emoji = "🟩"
            elif ratio < 0.66:
                emoji = "🟨"
            elif ratio < 0.9:
                emoji = "🟧"
            else:
                emoji = "🟥"

            return f"{emoji} {val_str}"

        # Color mapping for storage backends
        def get_storage_color(storage_name):
            if pd.isna(storage_name) or storage_name == "":
                return ""
            backend = (
                str(storage_name).split("/")[0]
                if "/" in str(storage_name)
                else str(storage_name)
            )
            colors = {
                "Memory": "🟣",
                "Memory+Sqlite(:memory:)": "🟤",
                "PickleFile": "🟢",
                "PickleFile_Signed": "🟢",
                "CloudpickleFile": "🔵",
                "CloudpickleFile_Signed": "🔵",
                "DillFile": "🟡",
                "DillFile_Signed": "🟡",
                "BagOfHoldingH5File": "🟠",
                "Sql": "🔴",
                "SqlFile": "🔴",
                "SqlMemory": "🔴",
                "Pickle+Sql": "🟢",
                "H5+Sql": "🟠",
            }
            return colors.get(backend, "⚪️")

        # Split out call storage (which only uses "/calls") from value storage
        is_call_storage = df["storage"].str.endswith("/calls", na=False)

        # Group categories using raw dataframe
        parent_categories = {
            "Digest Benchmarks": {
                "data": df[df["benchmark"] == "digest"],
                "index": "name",
            },
            "Value Storage Benchmarks": {
                "data": df[
                    df["benchmark"].str.startswith("storage_") & ~is_call_storage
                ],
                "index": "storage",
            },
            "Call Storage Benchmarks": {
                "data": df[
                    df["benchmark"].str.startswith("storage_") & is_call_storage
                ],
                "index": "storage",
            },
            "Integration Benchmarks": {
                "data": df[df["benchmark"].str.startswith("integration_")],
                "index": "name",
            },
        }

        def to_markdown_table(df):
            # Fallback markdown table generator if tabulate is not installed
            headers = df.columns.tolist()
            rows = df.values.tolist()

            header_row = "| " + " | ".join(str(h) for h in headers) + " |"
            separator_row = "| " + " | ".join("---" for _ in headers) + " |"

            table = [header_row, separator_row]
            for row in rows:
                table.append(
                    "| " + " | ".join(str(r) if pd.notna(r) else "" for r in row) + " |"
                )

            return "\n".join(table)

        def render_table(sub_df, index_col, parent_title):
            # For Digest benchmarks, we might just want a simple table without pivoting since 'benchmark' is just 'digest'
            if parent_title == "Digest Benchmarks":
                pivoted = sub_df.set_index(index_col)[["time"]]
                pivoted.columns = ["digest"]
                # Sort by time
                pivoted = pivoted.sort_values(by="digest", ascending=False)
            else:
                pivoted = sub_df.pivot(
                    index=index_col, columns="benchmark", values="time"
                )
                # Sort rows by sum
                pivoted["sum_time"] = pivoted.sum(axis=1)
                pivoted = pivoted.sort_values(by="sum_time", ascending=False)
                pivoted = pivoted.drop(columns=["sum_time"])

            if pivoted.empty:
                return

            # Format the dataframe
            formatted = pd.DataFrame(index=pivoted.index)

            # Keep track of color for the index if it has storage info
            formatted[index_col] = pivoted.index
            if index_col == "storage" or (
                index_col == "name" and parent_title == "Integration Benchmarks"
            ):
                formatted[index_col] = [
                    f"{get_storage_color(s)} {s}" if pd.notna(s) and s != "" else s
                    for s in formatted[index_col]
                ]

            for col in pivoted.columns:
                min_val = pivoted[col].min()
                max_val = pivoted[col].max()

                formatted[col] = [
                    (
                        add_color_to_cell(format_time(val), val, min_val, max_val)
                        if pd.notna(val)
                        else ""
                    )
                    for val in pivoted[col]
                ]

            # Remove prefixes from metric columns for cleaner tables
            new_columns = {}
            for col in formatted.columns:
                if col == index_col:
                    continue
                new_col = col.replace("storage_", "").replace("integration_", "")
                new_columns[col] = new_col
            formatted = formatted.rename(columns=new_columns)

            try:
                print(formatted.to_markdown(index=False))
            except ImportError:
                print(to_markdown_table(formatted))
            print("\n")

        print()
        for parent_title, info in parent_categories.items():
            sub_df = info["data"]
            if sub_df.empty:
                continue

            index_col = info["index"]

            print(f"<details>")
            print(f"<summary><b>{parent_title}</b></summary>\n")
            print('<div style="overflow-x: auto;">\n')

            if parent_title == "Value Storage Benchmarks":
                # Split storage column by '/'
                sub_df = sub_df.copy()
                sub_df[["storage_backend", "workload"]] = sub_df["storage"].str.split(
                    "/", n=1, expand=True
                )

                workloads = sub_df["workload"].unique()
                for workload in workloads:
                    if pd.isna(workload):
                        continue

                    print(f"<h4>Workload: {workload}</h4>\n")
                    workload_df = sub_df[sub_df["workload"] == workload].copy()
                    workload_df["storage"] = workload_df["storage_backend"]
                    render_table(workload_df, index_col, parent_title)
            elif parent_title == "Call Storage Benchmarks":
                sub_df = sub_df.copy()
                sub_df["storage"] = sub_df["storage"].str.replace("/calls", "")
                render_table(sub_df, index_col, parent_title)
            else:
                render_table(sub_df, index_col, parent_title)

            print("</div>")
            print("</details>\n")

        # Also save to CSV
        output_csv = os.path.join(benchmark_dir, "results.csv")
        final_df.to_csv(output_csv, index=False)
        print(f"Results saved to {output_csv}", file=sys.stderr)
    else:
        # Fallback if pandas is not available
        print("\nBenchmark Results (Pandas not available for pretty printing):\n")
        print("```json")
        print(json.dumps(all_results, indent=2))
        print("```")


if __name__ == "__main__":
    main()
