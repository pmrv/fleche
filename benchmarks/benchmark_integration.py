import time
import sys
import os
import json
import shutil
import tempfile
from statistics import median
import timeit
from functools import partial
from dataclasses import dataclass
import numpy as np

from fleche import fleche, cache
from fleche.caches import Cache, SizeLimitedCache
from fleche.storage import (
    ValueMemory,
    CallMemory,
    ValuePickleFile,
    ValueBagOfHoldingH5File,
    Sql,
    DestructuringMixin,
    ValueMixin,
    CallMixin,
)
from fleche.storage.memory import MemoryBackend
from fleche.storage.thread_safe import SerializingMixin


@dataclass(frozen=True)
class ValueMemoryRaw(DestructuringMixin, ValueMixin, MemoryBackend): ...


@dataclass(frozen=True)
class CallMemoryRaw(CallMixin, MemoryBackend): ...


@dataclass(frozen=True)
class ValueMemorySerializing(SerializingMixin, ValueMemoryRaw): ...


@dataclass(frozen=True)
class CallMemorySerializing(SerializingMixin, CallMemoryRaw): ...


@fleche
def lightweight_func(x):
    return x * 2


@fleche
def compute_heavy_func(n):
    # Deterministic CPU work — ~hundreds of microseconds, no scheduler noise.
    # Using ``time.sleep`` here would make the miss-overhead measurement
    # meaningless: the sleep's wake-up jitter dwarfs the framework overhead
    # we are trying to isolate.
    total = 0
    for i in range(20_000):
        total += (i * n) & 0xFFFF
    return total


@fleche
def data_heavy_func(n):
    # ``n`` controls the cache key only; output shape is fixed so every call
    # — whether a miss or a hit — moves the same amount of data through the
    # storage backend. Using ``np.random.rand`` avoids cheap-to-compress
    # constant data fooling backends like H5.
    return np.random.rand(100, 100)


def benchmark_integration(name, cache_obj, func, args, iterations=10):
    results = []

    raw_func = getattr(func, "__wrapped__", func)

    # Calibrate base function execution time using timeit (multiple averaged
    # runs for noise reduction). We pick one representative arg since the
    # function execution time is (by design) uniform across the supplied
    # args.
    sample_arg = args[0] if isinstance(args, list) else 0
    base_timer = timeit.Timer(partial(raw_func, sample_arg))
    base_number, _ = base_timer.autorange()
    base_number = max(1, min(base_number, 1000))
    base_repeats = base_timer.repeat(repeat=5, number=base_number)
    base_time = min(t / base_number for t in base_repeats)

    # 1. First Call (Miss). Each iteration must use a unique argument that is
    # not yet in the cache, otherwise we'd silently measure hits instead of
    # misses. Callers are responsible for supplying ``iterations`` distinct
    # args.
    miss_total_times = []
    for i in range(iterations):
        arg = args[i] if isinstance(args, list) else i

        start = time.perf_counter()
        with cache(cache_obj):
            func(arg)
        end = time.perf_counter()
        miss_total_times.append(end - start)

    # Use the median of (miss - base) without clamping. ``min`` of a
    # subtracted quantity is biased toward iterations where ``base``
    # happened to run slow; ``max(0, …)`` then hides the bias by zeroing
    # negatives. Median is a robust, sign-preserving estimator of the
    # framework overhead.
    miss_overhead = median(miss_total_times) - base_time

    results.append(
        {
            "benchmark": "integration_miss",
            "name": name,
            "iterations": iterations,
            "time": miss_overhead,
        }
    )

    # 2. Contains (Cache Check - Miss)
    contains_miss_times = []
    for i in range(iterations):
        arg = args[i] if isinstance(args, list) else i
        if isinstance(arg, int):
            arg = arg + iterations * 1000  # Ensure it's a miss
        else:
            arg = str(arg) + "__missing"  # Ensure it's a miss
        # Use .contains method exposed by @fleche to get the key and pass to contains
        start = time.perf_counter()
        with cache(cache_obj):
            func.contains(arg)
        end = time.perf_counter()
        contains_miss_times.append(end - start)

    results.append(
        {
            "benchmark": "integration_contains_miss",
            "name": name,
            "iterations": iterations,
            "time": min(contains_miss_times),
        }
    )

    # 3. Contains (Cache Check - Hit)
    contains_hit_times = []
    for i in range(iterations):
        arg = args[i] if isinstance(args, list) else i
        # Use .contains method exposed by @fleche to get the key and pass to contains
        start = time.perf_counter()
        with cache(cache_obj):
            func.contains(arg)
        end = time.perf_counter()
        contains_hit_times.append(end - start)

    results.append(
        {
            "benchmark": "integration_contains_hit",
            "name": name,
            "iterations": iterations,
            "time": min(contains_hit_times),
        }
    )

    # 4. Second Call (Hit)
    hit_times = []
    # Reuse the same args from above, they are now in cache
    for i in range(iterations):
        arg = args[i] if isinstance(args, list) else i

        start = time.perf_counter()
        with cache(cache_obj):
            func(arg)
        end = time.perf_counter()
        hit_times.append(end - start)

    results.append(
        {
            "benchmark": "integration_hit",
            "name": name,
            "iterations": iterations,
            "time": min(hit_times),
        }
    )

    return results


def main():
    print("Running Integration Benchmarks...", file=sys.stderr)
    all_results = []

    tmp_dir = tempfile.mkdtemp()

    try:
        # Configurations
        configs = [
            ("Memory(Raw)", Cache(ValueMemoryRaw({}), CallMemoryRaw({}))),
            ("Memory+Locked(Serializing)", Cache(ValueMemorySerializing({}), CallMemorySerializing({}))),
            ("Memory", Cache(ValueMemory({}), CallMemory({}))),
            ("Memory+Sqlite(:memory:)", Cache(ValueMemory({}), Sql())),
            (
                "Pickle+Sql",
                Cache(
                    ValuePickleFile.with_pickle(root=os.path.join(tmp_dir, "pickle")),
                    Sql(f"sqlite:///{tmp_dir}/db.sqlite"),
                ),
            ),
            (
                "H5+Sql",
                Cache(
                    ValueBagOfHoldingH5File(root=os.path.join(tmp_dir, "h5")),
                    Sql(f"sqlite:///{tmp_dir}/db_h5.sqlite"),
                ),
            ),
            # SizeLimitedCache: max_size smaller than iterations → evictions occur
            (
                "SizeLimitedCache(Memory,max=10)",
                SizeLimitedCache(ValueMemory({}), CallMemory({}), max_size=10),
            ),
            # SizeLimitedCache: max_size larger than iterations → no evictions
            (
                "SizeLimitedCache(Memory,max=100)",
                SizeLimitedCache(ValueMemory({}), CallMemory({}), max_size=100),
            ),
        ]

        for config_name, cache_inst in configs:
            # Lightweight
            all_results.extend(
                benchmark_integration(
                    f"{config_name}/lightweight",
                    cache_inst,
                    lightweight_func,
                    list(range(20)),
                    iterations=20,
                )
            )

            # Compute Heavy: function does deterministic CPU work, miss
            # measurement isolates framework overhead from execution.
            all_results.extend(
                benchmark_integration(
                    f"{config_name}/compute_heavy",
                    cache_inst,
                    compute_heavy_func,
                    list(range(20)),
                    iterations=20,
                )
            )

            # Data Heavy: each arg must be unique so every miss iteration
            # is a real miss. Output is a fixed-size 100x100 array.
            all_results.extend(
                benchmark_integration(
                    f"{config_name}/data_heavy",
                    cache_inst,
                    data_heavy_func,
                    list(range(20)),
                    iterations=20,
                )
            )

    finally:
        shutil.rmtree(tmp_dir)

    print(json.dumps(all_results, indent=2))


if __name__ == "__main__":
    main()
