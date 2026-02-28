
import time
import sys
import os
import json
import statistics
try:
    import numpy as np
except ImportError:
    np = None

from hypothesis import strategies as st

from fleche.digest import digest
from utils import st_nested_values, st_base_values, generate_examples

import timeit
from functools import partial

def benchmark(name, value, iterations=1000):
    # Warmup
    try:
        digest(value)
    except Exception as e:
        print(f"Skipping {name}: {e}")
        return None

    timer = timeit.Timer(partial(digest, value))

    # timeit.repeat runs the benchmark multiple times and returns a list of total times per repeat.
    # To get per-iteration times that we can calculate stddev from, we can run repeat(iterations, number=1).
    # This measures individual calls, similar to the hand-rolled loop but via timeit.
    times = timer.repeat(repeat=iterations, number=1)

    avg_time = statistics.median(times)
    stdev_time = statistics.stdev(times) if len(times) > 1 else 0

    return {
        "benchmark": "digest",
        "name": name,
        "iterations": iterations,
        "avg_time": avg_time,
        "stdev_time": stdev_time,
        "min_time": min(times),
        "max_time": max(times)
    }

def main():
    results = []

    print("Running Digest Benchmarks...", file=sys.stderr)

    # Simple types
    results.append(benchmark("Integer", 123456789))
    results.append(benchmark("String (short)", "hello world"))
    results.append(benchmark("String (long)", "x" * 10000))
    results.append(benchmark("Float", 123.456))
    results.append(benchmark("None", None))

    # Complex types
    results.append(benchmark("List (integers, small)", [1, 2, 3, 4, 5]))
    results.append(benchmark("List (integers, large)", list(range(1000))))
    results.append(benchmark("Dict (small)", {"a": 1, "b": 2}))

    # Numpy
    if np is not None:
        try:
            arr_small = np.array([1, 2, 3])
            arr_large = np.random.rand(100, 100)
            results.append(benchmark("Numpy (small)", arr_small))
            results.append(benchmark("Numpy (100x100)", arr_large))
        except ImportError:
            pass

    # Nested structures from hypothesis
    # We take one example
    try:
        nested_example = st_nested_values.example()
        res = benchmark("Nested (Random Hypothesis)", nested_example)
        if res:
            results.append(res)
    except Exception as e:
        print(f"Failed to generate/digest nested example: {e}", file=sys.stderr)

    # Filter None results
    results = [r for r in results if r is not None]

    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()
