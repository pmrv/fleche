import subprocess
import json
import sys
import os
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


def format_time(seconds: float) -> str:
    if seconds < 1e-6:
        return f"{seconds * 1e9:.2f} ns"
    elif seconds < 1e-3:
        return f"{seconds * 1e6:.2f} µs"
    elif seconds < 1:
        return f"{seconds * 1e3:.2f} ms"
    else:
        return f"{seconds:.2f} s"


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

    if pd:
        # Process results into a DataFrame for display
        df = pd.DataFrame(all_results)

        # Format times
        df["median"] = df["median_time"].apply(format_time)
        if "min_time" in df.columns:
            df["min"] = df["min_time"].apply(format_time)
        if "max_time" in df.columns:
            df["max"] = df["max_time"].apply(format_time)
        if "stdev_time" in df.columns:
            df["stdev"] = df["stdev_time"].apply(format_time)

        # Select and reorder columns
        display_cols = ["benchmark", "name", "storage", "iterations", "median"]
        # 'storage' column might not exist in all results
        if "storage" not in df.columns:
            df["storage"] = ""
        else:
            df["storage"] = df["storage"].fillna("")

        final_df = df[[c for c in display_cols if c in df.columns]]

        # Sort the dataframe by raw median time before grouping to preserve order (descending: largest value on top)
        df = df.sort_values(by="median_time", ascending=False)
        final_df = df[[c for c in display_cols if c in df.columns]]

        # We need the raw value to compute the color gradient, let's keep it in a parallel series
        # or compute the markdown explicitly row by row.
        # But we also have to drop it from final_df. We can map `avg_time` to colors.

        def get_color(value: float, min_val: float, max_val: float) -> str:
            import math

            # Using a simple perceptually uniform-ish colormap (viridis-like or simple heatmap)
            # We will use HSL to create a gradient from green (fast) to red (slow)
            if max_val == min_val:
                ratio = 0
            else:
                # log scale might be better for times, but let's use linear first or slightly compressed
                ratio = (value - min_val) / (max_val - min_val)

            # 120 (Green) to 0 (Red)
            hue = 120 - int(ratio * 120)
            return f"hsl({hue}, 70%, 50%)"

        def add_color_to_cell(
            val_str: str, raw_val: float, min_val: float, max_val: float
        ) -> str:
            color = get_color(raw_val, min_val, max_val)
            # Github Markdown supports img shields or html. But wait, Github Markdown strips most style tags and raw CSS on tables!
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
                "CloudpickleFile": "🔵",
                "BagOfHoldingH5File": "🟠",
                "Sql": "🔴",
                "SqlFile": "🔴",
                "SqlMemory": "🔴",
                "Pickle+Sql": "🟢",
                "H5+Sql": "🟠",
            }
            return colors.get(backend, "⚪️")

        # Split out call storage (which only uses "/calls") from value storage
        is_call_storage = df['storage'].str.endswith('/calls', na=False)

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

        print()
        for parent_title, info in parent_categories.items():
            sub_df = info["data"]
            if sub_df.empty:
                continue

            index_col = info["index"]

            print(f"<details>")
            print(f"<summary><b>{parent_title}</b></summary>\n")
            print('<div style="overflow-x: auto;">\n')

            # For Digest benchmarks, we might just want a simple table without pivoting since 'benchmark' is just 'digest'
            if parent_title == "Digest Benchmarks":
                pivoted = sub_df.set_index(index_col)[["median_time"]]
                pivoted.columns = ["digest"]
                # Sort by time
                pivoted = pivoted.sort_values(by="digest", ascending=False)
            else:
                pivoted = sub_df.pivot(
                    index=index_col, columns="benchmark", values="median_time"
                )
                # Sort rows by sum
                pivoted["sum_time"] = pivoted.sum(axis=1)
                pivoted = pivoted.sort_values(by="sum_time", ascending=False)
                pivoted = pivoted.drop(columns=["sum_time"])

            if pivoted.empty:
                print("</div>")
                print("</details>\n")
                continue

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

            try:
                print(formatted.to_markdown(index=False))
            except ImportError:
                print(to_markdown_table(formatted))
            print("\n")

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
