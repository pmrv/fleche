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

    old_df = None
    if pd:
        old_results_path = os.path.join(benchmark_dir, "results.csv")
        if os.path.exists(old_results_path):
            try:
                old_df = pd.read_csv(old_results_path)
            except Exception as e:
                print(f"Failed to read existing results.csv: {e}", file=sys.stderr)

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
        display_cols = ["topic", "configuration", "workload", "function", "time"]
        # 'storage' column might not exist in all results
        if "storage" not in df.columns:
            df["storage"] = ""
        else:
            df["storage"] = df["storage"].fillna("")

        # Sort the dataframe by time before processing to preserve order (descending: largest value on top)
        df = df.sort_values(by="time", ascending=False)

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

        rows = []
        for _, row in df.iterrows():
            b = row["benchmark"]
            n = row.get("name", "")
            if pd.isna(n):
                n = ""
            s = row.get("storage", "")
            if pd.isna(s):
                s = ""
            time_val = row["time"]

            if b == "digest":
                topic = "Digest"
                config = ""
                workload = n
                function = "digest"
            elif b.startswith("storage_"):
                function = b.replace("storage_", "")
                if s.endswith("/calls"):
                    topic = "Call Storage"
                    parts = s.split("/")
                    config = parts[0]
                    workload = parts[1] if len(parts) > 1 else ""
                else:
                    topic = "Value Storage"
                    parts = s.split("/")
                    config = parts[0]
                    workload = parts[1] if len(parts) > 1 else ""
            elif b.startswith("integration_"):
                topic = "Integration"
                function = b.replace("integration_", "")
                parts = str(n).split("/")
                config = parts[0]
                workload = parts[1] if len(parts) > 1 else ""
            else:
                topic = "Other"
                config = ""
                workload = ""
                function = b

            # Apply formatting and color mapping
            colored_config = (
                f"{get_storage_color(config)} {config}" if config else config
            )
            formatted_time = format_time(time_val)

            rows.append(
                {
                    "topic": topic,
                    "configuration": colored_config,
                    "workload": workload,
                    "function": function,
                    "time": formatted_time,
                }
            )

        parsed_df = pd.DataFrame(rows)

        def to_markdown_table(df_to_render):
            # Fallback markdown table generator if tabulate is not installed
            headers = df_to_render.columns.tolist()
            rows = df_to_render.values.tolist()

            header_row = "| " + " | ".join(str(h) for h in headers) + " |"
            separator_row = "| " + " | ".join("---" for _ in headers) + " |"

            table = [header_row, separator_row]
            for row in rows:
                table.append(
                    "| " + " | ".join(str(r) if pd.notna(r) else "" for r in row) + " |"
                )

            return "\n".join(table)

        print()

        # Compare with old_df to find significant changes
        if old_df is not None and not old_df.empty:
            try:
                # Ensure merge columns are strings to match safely
                merge_cols = ["benchmark", "name", "storage"]
                for col in merge_cols:
                    if col in final_df.columns:
                        final_df[col] = final_df[col].fillna("").astype(str)
                    if col in old_df.columns:
                        old_df[col] = old_df[col].fillna("").astype(str)

                compare_df = pd.merge(
                    final_df, old_df, on=merge_cols, suffixes=("_new", "_old")
                )
                # Filter out those where old time is 0 to avoid division by zero
                compare_df = compare_df[compare_df["time_old"] > 0].copy()
                compare_df["% Change"] = (
                    (compare_df["time_new"] - compare_df["time_old"])
                    / compare_df["time_old"]
                ) * 100

                significant_changes = compare_df[
                    compare_df["% Change"].abs() > 5.0
                ].copy()

                if not significant_changes.empty:
                    significant_changes = significant_changes.sort_values(
                        by="% Change", key=abs, ascending=False
                    )

                    def format_change(val):
                        sign = "+" if val > 0 else ""
                        color = (
                            "🔴" if val > 0 else "🟢"
                        )  # red for slower, green for faster
                        return f"{color} {sign}{val:.1f}%"

                    significant_changes["% Change"] = significant_changes[
                        "% Change"
                    ].apply(format_change)
                    significant_changes["Old Time"] = significant_changes[
                        "time_old"
                    ].apply(format_time)
                    significant_changes["New Time"] = significant_changes[
                        "time_new"
                    ].apply(format_time)

                    display_cols = [
                        "benchmark",
                        "name",
                        "storage",
                        "Old Time",
                        "New Time",
                        "% Change",
                    ]
                    display_changes = significant_changes[
                        [c for c in display_cols if c in significant_changes.columns]
                    ]

                    print("<details open>")
                    print("<summary><b>Significant Changes (>5%)</b></summary>\n")
                    print('<div style="overflow-x: auto;">\n')
                    try:
                        print(display_changes.to_markdown(index=False))
                    except ImportError:
                        print(to_markdown_table(display_changes))
                    print("\n</div>")
                    print("</details>\n")
            except Exception as e:
                print(f"Error computing significant changes: {e}", file=sys.stderr)

        for parent_title, info in parent_categories.items():
            sub_df = info["data"]
            if sub_df.empty:
                continue

            index_col = info["index"]

            print("<details>")
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
            elif parent_title == "Integration Benchmarks":
                # Split name column by '/'
                sub_df = sub_df.copy()
                sub_df[["storage_backend", "workload"]] = sub_df["name"].str.split(
                    "/", n=1, expand=True
                )

                workloads = sub_df["workload"].unique()
                for workload in workloads:
                    if pd.isna(workload):
                        continue

                    print(f"<h4>Workload: {workload}</h4>\n")
                    workload_df = sub_df[sub_df["workload"] == workload].copy()
                    workload_df["name"] = workload_df["storage_backend"]
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
        # Ensure we only save the columns requested. Strip color emojis from configuration
        clean_df = parsed_df.copy()
        clean_df["configuration"] = clean_df["configuration"].str.replace(
            r"^[^\w\s]+\s+", "", regex=True
        )

        clean_df.to_csv(output_csv, index=False)
        print(f"Results saved to {output_csv}", file=sys.stderr)
    else:
        # Fallback if pandas is not available
        print("\nBenchmark Results (Pandas not available for pretty printing):\n")
        print("```json")
        print(json.dumps(all_results, indent=2))
        print("```")


if __name__ == "__main__":
    main()
