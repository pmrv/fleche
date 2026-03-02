
import time
import sys
import os
import json
import shutil
import tempfile
import gc
from pathlib import Path
from typing import Any

from fleche.storage import Memory, PickleFile, CloudpickleFile, Sql, BagOfHoldingH5File
from fleche.digest import digest
from fleche.call import Call
import numpy as np
import timeit
from functools import partial

def benchmark_storage_ops(storage_name, storage_factory, values_to_store):
    results = []

    # Create temp dir for storage
    tmp_dir = tempfile.mkdtemp()
    try:
        storage = storage_factory(tmp_dir)

        # Pre-compute keys
        keys = []
        for val in values_to_store:
            try:
                keys.append(digest(val))
            except Exception as e:
                print(f"Error digesting for {storage_name}: {e}", file=sys.stderr)
                keys.append(None)

        valid_items = [(val, k) for val, k in zip(values_to_store, keys) if k is not None]

        if not valid_items:
            return []

        # Benchmark Save
        save_times = []
        for val, key in valid_items:
            timer = timeit.Timer(partial(storage.save, val, key))
            # Use smaller number for storage since it's much slower than digest
            number = 10
            times = timer.repeat(repeat=3, number=number)
            save_times.extend([t / number for t in times])

        if save_times:
            results.append({
                "benchmark": "storage_save",
                "storage": storage_name,
                "iterations": len(valid_items) * 30,
                "time": min(save_times)
            })

        # Benchmark Load
        load_times = []
        for _, key in valid_items:
            try:
                timer = timeit.Timer(partial(storage.load, key))
                number = 10
                times = timer.repeat(repeat=3, number=number)
                load_times.extend([t / number for t in times])
            except Exception as e:
                print(f"Error loading from {storage_name}: {e}", file=sys.stderr)
                continue

        if load_times:
            results.append({
                "benchmark": "storage_load",
                "storage": storage_name,
                "iterations": len(load_times),
                "time": min(load_times)
            })

        # Benchmark Evict
        evict_times = []
        for _, key in valid_items:
            try:
                # Eviction removes it, so we can't repeat it simply with timeit without setup.
                # Since evict alters state, we need to do a manual setup and single pass per iteration,
                # or just use a simple loop. Timeit allows setup string, but we just want to measure evict.
                # Best way for evict is to time one execution per key.
                start = time.perf_counter()
                storage.evict(key)
                end = time.perf_counter()
                evict_times.append(end - start)
            except NotImplementedError:
                break
            except Exception as e:
                 print(f"Error evicting from {storage_name}: {e}", file=sys.stderr)
                 continue

        if evict_times:
             results.append({
                "benchmark": "storage_evict",
                "storage": storage_name,
                "iterations": len(evict_times),
                "time": min(evict_times)
            })

    finally:
        shutil.rmtree(tmp_dir)

    return results

def main():
    print("Running Storage Benchmarks...", file=sys.stderr)

    # Test Data
    small_data = [f"value_{i}" for i in range(100)]

    # Generate some complex nested structures
    from utils import st_nested_values
    try:
        nested_data = [st_nested_values.example() for _ in range(50)]
    except Exception as e:
        print(f"Failed to generate nested data: {e}", file=sys.stderr)
        nested_data = [{"a": 1, "b": [2, 3], "c": {"d": "test"}}] * 50

    workloads = [
        ("small_strings", small_data),
        ("nested_structures", nested_data)
    ]

    if np:
        large_data = [np.random.rand(100, 100) for _ in range(20)] # 20 large arrays
        workloads.append(("numpy_arrays", large_data))

    factories = {
        "Memory": lambda path: Memory({}),
        "PickleFile": lambda path: PickleFile(path),
        "CloudpickleFile": lambda path: CloudpickleFile(path),
        # Sql is a CallStorage, skipped for general values
        "BagOfHoldingH5File": lambda path: BagOfHoldingH5File(path) # removed project arg
    }

    all_results = []

    for workload_name, data in workloads:
        for storage_name, factory in factories.items():

            try:
                # Force GC to minimize interference
                gc.collect()
                results = benchmark_storage_ops(f"{storage_name}/{workload_name}", factory, data)
                all_results.extend(results)
            except Exception as e:
                print(f"Failed {storage_name}/{workload_name}: {e}", file=sys.stderr)

    # Test Sql specifically with Call objects
    calls_data = []
    for i in range(50):
        c = Call(name="func", arguments={"a": i}, module="mod", version=1)
        calls_data.append(c)

    # Let's do Sql benchmark separately
    tmp_dir = tempfile.mkdtemp()
    try:
        for storage_label, url in [
            ("SqlFile/calls", f"sqlite:///{tmp_dir}/db.sqlite"),
            ("SqlMemory/calls", "sqlite:///:memory:")
        ]:
            sql_results = []
            try:
                storage = Sql(url)

                save_times = []
                keys = []
                for c in calls_data:
                    timer = timeit.Timer(partial(storage.save, c))
                    number = 10
                    times = timer.repeat(repeat=3, number=number)
                    save_times.extend([t / number for t in times])
                    keys.append(c.to_lookup_key()) # Call keys are their lookup key

                sql_results.append({
                    "benchmark": "storage_save",
                    "storage": storage_label,
                    "iterations": len(calls_data) * 30,
                    "time": min(save_times)
                })

                load_times = []
                for key in keys:
                    timer = timeit.Timer(partial(storage.load, key))
                    number = 10
                    times = timer.repeat(repeat=3, number=number)
                    load_times.extend([t / number for t in times])

                sql_results.append({
                    "benchmark": "storage_load",
                    "storage": storage_label,
                    "iterations": len(keys) * 30,
                    "time": min(load_times)
                })

                # Sql supports evict(key)
                evict_times = []
                for key in keys:
                    # Single run for eviction
                    start = time.perf_counter()
                    storage.evict(key)
                    end = time.perf_counter()
                    evict_times.append(end - start)

                sql_results.append({
                    "benchmark": "storage_evict",
                    "storage": storage_label,
                    "iterations": len(evict_times),
                    "time": min(evict_times)
                })

                all_results.extend(sql_results)

            except Exception as e:
                import traceback
                print(f"Failed {storage_label}: {e}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
    finally:
        shutil.rmtree(tmp_dir)

    print(json.dumps(all_results, indent=2))

if __name__ == "__main__":
    main()
