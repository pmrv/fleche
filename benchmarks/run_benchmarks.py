
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

        # Group categories
        categories = {
            "Digest Benchmarks": final_df[final_df['benchmark'] == 'digest'],
            "Storage Benchmarks": final_df[final_df['benchmark'].str.startswith('storage_')],
            "Integration Benchmarks": final_df[final_df['benchmark'].str.startswith('integration_')]
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
        for title, sub_df in categories.items():
            if sub_df.empty:
                continue

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
