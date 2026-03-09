import subprocess
import json
import sys
import os
import math
from typing import List, Dict

import pandas as pd


def run_script(script_path: str) -> List[Dict]:
    print(f"Running {script_path}...", file=sys.stderr)
    result = None
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
        if result is not None:
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

    # Process results into a DataFrame for display
    df = pd.DataFrame(all_results)

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
        colored_config = f"{get_storage_color(config)} {config}" if config else config
        formatted_time = format_time(time_val)

        rows.append(
            {
                "topic": topic,
                "configuration": colored_config,
                "workload": workload,
                "function": function,
                "time": time_val,
                "time_formatted": formatted_time,
            }
        )

    parsed_df = pd.DataFrame(rows)

    print()
    for (topic, wkl), group in parsed_df.groupby(["topic", "workload"]):
        summary_title = f"{topic} ({wkl})" if wkl else topic
        print(f"<details><summary>{summary_title}</summary>\n")

        # Pivot on function
        pivot_df = group.pivot(
            index=["configuration", "workload"], columns="function", values="time"
        ).reset_index()

        # Drop completely empty columns
        for col in ["configuration"]:
            if pivot_df[col].astype(str).str.strip().eq("").all():
                pivot_df = pivot_df.drop(columns=[col])

        # Apply coloring
        for col in pivot_df.columns:
            if col in ["configuration", "workload"]:
                continue

            min_val = pivot_df[col].min()
            max_val = pivot_df[col].max()

            def format_and_color(val, min_v, max_v):
                if pd.isna(val):
                    return ""
                val_str = format_time(val)
                return add_color_to_cell(val_str, val, min_v, max_v)

            pivot_df[col] = pivot_df[col].apply(
                lambda x: format_and_color(x, min_val, max_val)
            )

        print(pivot_df.to_markdown(index=False))
        print("\n</details>\n")

    # Also save to CSV
    output_csv = os.path.join(benchmark_dir, "results.csv")
    # Ensure we only save the columns requested. Strip color emojis from configuration
    clean_df = parsed_df.copy().drop(columns=["time_formatted"])
    clean_df["configuration"] = clean_df["configuration"].str.replace(
        r"^[^\w\s]+\s+", "", regex=True
    )

    clean_df.to_csv(output_csv, index=False)
    print(f"Results saved to {output_csv}", file=sys.stderr)


if __name__ == "__main__":
    main()
