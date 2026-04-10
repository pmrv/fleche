import sys
import json
from statistics import median

from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays as st_arrays

from fleche.digest import digest
from utils import st_nested_values, st_nested_values, generate_examples

import timeit


def benchmark(name, strategy):
    try:
        digest(generate_examples(strategy))
    except Exception as e:
        print(f"Skipping {name}: {e}")
        return None

    timer = timeit.Timer(
        stmt="digest(value)",
        setup="value = generate_examples(strategy)",
        globals={
            "generate_examples": generate_examples,
            "strategy": strategy,
            "digest": digest,
        },
    )

    # Determine a good number of iterations automatically
    number, _ = timer.autorange()

    repeats = 3
    # Cap number to avoid overly long runs for expensive operations
    if number > 1000:
        number = 1000
    times = timer.repeat(repeat=repeats, number=number)

    # Calculate time per call
    times_per_call = [t / number for t in times]

    return {
        "benchmark": "digest",
        "name": name,
        "iterations": number * repeats,
        "time": median(times_per_call),
    }


def main():
    results = []

    print("Running Digest Benchmarks...", file=sys.stderr)

    # Simple types
    results.append(benchmark("Integer", st.integers()))
    results.append(benchmark("String (len<100)", st.text(max_size=100)))
    results.append(benchmark("String (len>100)", st.text(min_size=100)))
    results.append(benchmark("Float", st.floats()))
    results.append(benchmark("None", st.none()))

    # Complex types
    results.append(
        benchmark("List (integers, len<100)", st.lists(st.integers(), max_size=100))
    )
    results.append(
        benchmark("List (integers, len>100)", st.lists(st.integers(), min_size=100))
    )
    results.append(
        benchmark(
            "Dict (small)", st.dictionaries(st.text(max_size=10), st.text(max_size=10))
        )
    )

    # Numpy
    results.append(
        benchmark(
            "Numpy (integers, len<100)",
            st_arrays(int, st.integers(min_value=0, max_value=100)),
        )
    )
    results.append(
        benchmark(
            "Numpy (integers, len>100)",
            st_arrays(int, st.integers(min_value=100, max_value=10_000)),
        )
    )
    results.append(benchmark("Nested (Random Hypothesis)", st_nested_values))

    # Filter None results
    results = [r for r in results if r is not None]

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
