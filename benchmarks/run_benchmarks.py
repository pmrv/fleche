
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
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            check=True
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
        "benchmark_integration.py"
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
        df['median'] = df['median_time'].apply(format_time)
        if 'min_time' in df.columns:
            df['min'] = df['min_time'].apply(format_time)
        if 'max_time' in df.columns:
            df['max'] = df['max_time'].apply(format_time)
        if 'stdev_time' in df.columns:
            df['stdev'] = df['stdev_time'].apply(format_time)

        # Select and reorder columns
        display_cols = ['benchmark', 'name', 'storage', 'iterations', 'median']
        # 'storage' column might not exist in all results
        if 'storage' not in df.columns:
            df['storage'] = ""
        else:
            df['storage'] = df['storage'].fillna("")

        final_df = df[[c for c in display_cols if c in df.columns]]

        # Sort the dataframe by raw median time before grouping to preserve order (descending: largest value on top)
        df = df.sort_values(by='median_time', ascending=False)
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

        def add_color_to_cell(val_str: str, raw_val: float, min_val: float, max_val: float) -> str:
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
            backend = str(storage_name).split('/')[0] if '/' in str(storage_name) else str(storage_name)
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

        # Split out call storage (which only uses "Sql/calls") from value storage
        is_call_storage = df['storage'].str.endswith('/calls', na=False)

        # Group categories using raw dataframe to keep avg_time for coloring
        categories_raw = {
            "Digest Benchmarks": df[df['benchmark'] == 'digest'],
            "Storage Load": df[(df['benchmark'] == 'storage_load') & ~is_call_storage],
            "Storage Save": df[(df['benchmark'] == 'storage_save') & ~is_call_storage],
            "Storage Evict": df[(df['benchmark'] == 'storage_evict') & ~is_call_storage],
            "Call Storage Load": df[(df['benchmark'] == 'storage_load') & is_call_storage],
            "Call Storage Save": df[(df['benchmark'] == 'storage_save') & is_call_storage],
            "Call Storage Evict": df[(df['benchmark'] == 'storage_evict') & is_call_storage],
            "Integration Hit": df[df['benchmark'] == 'integration_hit'],
            "Integration Miss": df[df['benchmark'] == 'integration_miss']
        }

        # Parent categories for folding
        parent_categories = {
            "Digest Benchmarks": ["Digest Benchmarks"],
            "Value Storage Benchmarks": ["Storage Load", "Storage Save", "Storage Evict"],
            "Call Storage Benchmarks": ["Call Storage Load", "Call Storage Save", "Call Storage Evict"],
            "Integration Benchmarks": ["Integration Hit", "Integration Miss"]
        }

        def to_markdown_table(df):
            # Fallback markdown table generator if tabulate is not installed
            headers = df.columns.tolist()
            rows = df.values.tolist()

            header_row = "| " + " | ".join(str(h) for h in headers) + " |"
            separator_row = "| " + " | ".join("---" for _ in headers) + " |"

            table = [header_row, separator_row]
            for row in rows:
                table.append("| " + " | ".join(str(r) if pd.notna(r) else "" for r in row) + " |")

            return "\n".join(table)

        print()
        for parent_title, child_keys in parent_categories.items():
            # Check if any child has data
            if not any(not categories_raw[k].empty for k in child_keys):
                continue

            print(f"<details>")
            print(f"<summary><b>{parent_title}</b></summary>\n")
            print('<div style="overflow-x: auto;">\n')

            for title in child_keys:
                raw_df = categories_raw[title]
                if raw_df.empty:
                    continue

                print(f"### {title}\n")

                # Prepare formatted slice
                sub_df = final_df.loc[raw_df.index].copy()

                # Add emoji gradient to median
                min_val = raw_df['median_time'].min()
                max_val = raw_df['median_time'].max()

                sub_df['median'] = [add_color_to_cell(a, r, min_val, max_val) for a, r in zip(sub_df['median'], raw_df['median_time'])]

                # Apply storage color
                if 'storage' in sub_df.columns:
                    sub_df['storage'] = [f"{get_storage_color(s)} {s}" if pd.notna(s) and s != "" else s for s in sub_df['storage']]

                # We can also color 'name' column if it encodes storage, but integration tests encode it in 'name'
                if title.startswith('Integration'):
                    if 'name' in sub_df.columns:
                        sub_df['name'] = [f"{get_storage_color(s)} {s}" if pd.notna(s) and s != "" else s for s in sub_df['name']]

                # Drop empty columns
                for col in sub_df.columns:
                    # pandas replaces empty string with NaN sometimes, or if all are empty string
                    if (sub_df[col] == "").all() or sub_df[col].isna().all():
                        sub_df = sub_df.drop(columns=[col])

                # Drop iterations as requested
                if 'iterations' in sub_df.columns:
                    sub_df = sub_df.drop(columns=['iterations'])

                # Drop benchmark column since it's redundant with the child title
                if 'benchmark' in sub_df.columns:
                    sub_df = sub_df.drop(columns=['benchmark'])

                try:
                    print(sub_df.to_markdown(index=False))
                except ImportError:
                    print(to_markdown_table(sub_df))
                print("\n")

            print('</div>')
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
