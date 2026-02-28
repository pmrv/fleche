
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
        df['avg'] = df['avg_time'].apply(format_time)
        df['min'] = df['min_time'].apply(format_time)
        df['max'] = df['max_time'].apply(format_time)
        df['stdev'] = df['stdev_time'].apply(format_time)

        # Select and reorder columns
        display_cols = ['benchmark', 'name', 'storage', 'iterations', 'avg', 'stdev', 'min', 'max']
        # 'storage' column might not exist in all results
        if 'storage' not in df.columns:
            df['storage'] = ""
        else:
            df['storage'] = df['storage'].fillna("")

        final_df = df[[c for c in display_cols if c in df.columns]]

        # Sort the dataframe by raw average time before grouping to preserve order
        df = df.sort_values(by='avg_time', ascending=True)
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

        # Group categories using raw dataframe to keep avg_time for coloring
        categories_raw = {
            "Digest Benchmarks": df[df['benchmark'] == 'digest'],
            "Storage Benchmarks": df[df['benchmark'].str.startswith('storage_')],
            "Integration Benchmarks": df[df['benchmark'].str.startswith('integration_')]
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
        for title, raw_df in categories_raw.items():
            if raw_df.empty:
                continue

            # Prepare formatted slice
            sub_df = final_df.loc[raw_df.index].copy()

            # Add emoji gradient to avg
            min_val = raw_df['avg_time'].min()
            max_val = raw_df['avg_time'].max()

            # We can use HTML image for better gradient instead of emoji?
            # GitHub supports `![](https://placehold.co/15x15/COLOR/COLOR.png)`
            # Let's use the placehold.co or simple html styling for the cell if we could, but markdown tables don't support row styles.
            # Let's use image tags!

            def get_color_hex(value: float, min_val: float, max_val: float) -> str:
                # simple red to green gradient (or green to red)
                if max_val == min_val:
                    ratio = 0
                else:
                    ratio = (value - min_val) / (max_val - min_val)

                # HSL to RGB approximation for Green (120) to Red (0)
                # Green is 0, 255, 0. Red is 255, 0, 0
                r = int(ratio * 255)
                g = int((1 - ratio) * 255)
                return f"{r:02x}{g:02x}00"

            # Alternatively, since placehold.co might fail, let's use the HTML colored text block.
            # github markdown does not support `color` or `background-color` in standard tags.
            # We will use the emoji gradient as a safe and reliable method.

            sub_df['avg'] = [add_color_to_cell(a, r, min_val, max_val) for a, r in zip(sub_df['avg'], raw_df['avg_time'])]

            # Drop empty columns
            for col in sub_df.columns:
                # pandas replaces empty string with NaN sometimes, or if all are empty string
                if (sub_df[col] == "").all() or sub_df[col].isna().all():
                    sub_df = sub_df.drop(columns=[col])

            # Drop iterations as requested
            if 'iterations' in sub_df.columns:
                sub_df = sub_df.drop(columns=['iterations'])

            # If the category is digest, benchmark column might be redundant
            if title == "Digest Benchmarks" and 'benchmark' in sub_df.columns:
                sub_df = sub_df.drop(columns=['benchmark'])

            # Print Markdown fold
            print(f"<details>")
            print(f"<summary><b>{title}</b></summary>\n")
            try:
                print(sub_df.to_markdown(index=False))
            except ImportError:
                print(to_markdown_table(sub_df))
            print()
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
