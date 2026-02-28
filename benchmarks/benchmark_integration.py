
import time
import sys
import os
import json
import statistics
import shutil
import tempfile
import gc
from typing import Any
import numpy as np

from fleche import fleche, cache
from fleche.caches import Cache
from fleche.storage import Memory, PickleFile, Sql, BagOfHoldingH5File

# Define some test functions
@fleche
def lightweight_func(x):
    return x * 2

@fleche
def compute_heavy_func(n):
    # Simulate heavy computation
    time.sleep(0.01)
    return n * n

@fleche
def data_heavy_func(n):
    # Returns a large numpy array
    return np.random.rand(n, n)

def benchmark_integration(name, cache_obj, func, args, iterations=10):
    results = []

    # Pre-calculate base execution times for the function (without cache overhead)
    base_times = []
    raw_func = getattr(func, "__wrapped__", func)

    for i in range(iterations):
        arg = args[i] if isinstance(args, list) else i
        start = time.perf_counter()
        raw_func(arg)
        end = time.perf_counter()
        base_times.append(end - start)

    # We will subtract the average base execution time from the miss times
    # to isolate the framework overhead (fleche logic + storage save).
    # Since hit times don't execute the function, they don't need this adjustment.
    avg_base_time = statistics.mean(base_times)

    # 1. First Call (Miss)
    miss_overhead_times = []
    for i in range(iterations):
        # vary argument to ensure miss
        arg = args[i] if isinstance(args, list) else i

        start = time.perf_counter()
        with cache(cache_obj):
            func(arg)
        end = time.perf_counter()

        # Calculate overhead by subtracting base execution time for this specific call
        # Or just subtract the general average. Subtracting specific base time might be better
        # if execution time varies widely, but here it's fine to subtract the specific one since
        # we ran the same arguments in the same order.
        miss_overhead_times.append(max(0, (end - start) - base_times[i]))

    results.append({
        "benchmark": "integration_miss",
        "name": name,
        "iterations": iterations,
        "avg_time": statistics.median(miss_overhead_times),
        "stdev_time": statistics.stdev(miss_overhead_times) if len(miss_overhead_times) > 1 else 0,
        "min_time": min(miss_overhead_times),
        "max_time": max(miss_overhead_times)
    })

    # 2. Second Call (Hit)
    hit_times = []
    # Reuse the same args from above, they are now in cache
    for i in range(iterations):
        arg = args[i] if isinstance(args, list) else i

        start = time.perf_counter()
        with cache(cache_obj):
            func(arg)
        end = time.perf_counter()
        hit_times.append(end - start)

    results.append({
        "benchmark": "integration_hit",
        "name": name,
        "iterations": iterations,
        "avg_time": statistics.median(hit_times),
        "stdev_time": statistics.stdev(hit_times) if len(hit_times) > 1 else 0,
        "min_time": min(hit_times),
        "max_time": max(hit_times)
    })

    return results

def main():
    print("Running Integration Benchmarks...", file=sys.stderr)
    all_results = []

    tmp_dir = tempfile.mkdtemp()

    try:
        # Configurations
        configs = [
            ("Memory", Cache(Memory({}), Memory({}))),
            ("Pickle+Sql", Cache(PickleFile(os.path.join(tmp_dir, "pickle")), Sql(f"sqlite:///{tmp_dir}/db.sqlite"))),
            ("H5+Sql", Cache(BagOfHoldingH5File(os.path.join(tmp_dir, "h5")), Sql(f"sqlite:///{tmp_dir}/db_h5.sqlite")))
        ]

        for config_name, cache_inst in configs:
            # Lightweight
            all_results.extend(benchmark_integration(f"{config_name}/lightweight", cache_inst, lightweight_func, list(range(20)), iterations=20))

            # Compute Heavy
            # We subtract the sleep time to see overhead? No, total time is what matters for user usually,
            # but for benchmarking the framework overhead, maybe we should use a function without sleep but still "heavy"?
            # Or just accept that "miss" time includes execution time.
            # Ideally we compare "miss time" vs "raw execution time".
            # But here we just compare different storage backends for the same function.
            all_results.extend(benchmark_integration(f"{config_name}/compute_heavy", cache_inst, compute_heavy_func, list(range(20)), iterations=20))

            # Data Heavy
            # args are size N
            if np is not None:
                all_results.extend(benchmark_integration(f"{config_name}/data_heavy", cache_inst, data_heavy_func, [100] * 20, iterations=20)) # 100x100 array

    finally:
        shutil.rmtree(tmp_dir)

    print(json.dumps(all_results, indent=2))

if __name__ == "__main__":
    main()
