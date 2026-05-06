import subprocess
import json
import sys
import os
import math
from typing import List, Dict

import pandas as pd


def run_script(script_path: str) -> List[Dict]:
    print(f"Running {script_path}...", file=sys.stderr)
    # Forward stderr in real time so slow sub-scripts give feedback, and a
    # failure surfaces its full traceback instead of being swallowed.
    result = subprocess.run(
        [sys.executable, script_path], capture_output=True, text=True
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise RuntimeError(
            f"{script_path} exited with status {result.returncode}; "
            "its table would be missing from the report, aborting."
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        sys.stderr.write(result.stderr)
        sys.stderr.write("--- stdout ---\n")
        sys.stderr.write(result.stdout)
        raise RuntimeError(
            f"{script_path} produced invalid JSON: {e}; "
            "its table would be missing from the report, aborting."
        ) from e


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

    def add_color_to_cell(
        val_str: str, raw_val: float, min_val: float, max_val: float
    ) -> str:
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
            "Memory+Locked(Serializing)": "🟪",
            "Memory+Locked(PerKey)": "🟪",
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
            "SizeLimitedCache(Memory,max=10)": "🟣",
            "SizeLimitedCache(Memory,max=100)": "🟣",
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

        rows.append(
            {
                "topic": topic,
                "configuration": colored_config,
                "workload": workload,
                "function": function,
                "time": time_val,
            }
        )

    parsed_df = pd.DataFrame(rows)

    print()

    def to_pretty_markdown(df, index: str):
        """Turn raw timing table into something that can be shown in markdown prettily."""

        min_val = df["time"].min()
        max_val = df["time"].max()

        def format_and_color(val, min_v, max_v):
            if pd.isna(val):
                return ""
            val_str = format_time(val)
            return add_color_to_cell(val_str, val, min_v, max_v)

        df.sort_values("time", inplace=True, ascending=False)
        df["time"] = df["time"].apply(
            lambda x: format_and_color(x, min_val, max_val)
        )

        # Pivot on function
        df = df.pivot(
            index=index, columns="function", values="time"
        ).reset_index()

        return df.to_markdown(index=False)

    for topic, topic_df in parsed_df.groupby("topic"):
        print(f"<details><summary>{topic}</summary>\n")

        if topic == "Digest":
            print(to_pretty_markdown(topic_df.drop("configuration", axis="columns"), index="workload"))
        else:
            for workload, workload_df in topic_df.groupby("workload"):
                print(f"## {workload}")
                print(to_pretty_markdown(workload_df, index="configuration"))

        print("\n</details>\n")

    # Also save to CSV
    output_csv = os.path.join(benchmark_dir, "results.csv")
    # Ensure we only save the columns requested. Strip color emojis from configuration
    parsed_df["configuration"] = parsed_df["configuration"].str.replace(
        r"^[^\w\s]+\s+", "", regex=True
    )

    parsed_df.to_csv(output_csv, index=False)
    print(f"Results saved to {output_csv}", file=sys.stderr)


if __name__ == "__main__":
    main()
