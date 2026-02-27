
import time
import sys
import os
import json
import statistics
import shutil
import tempfile
import gc
from pathlib import Path
from typing import Any

from fleche.storage import Memory, PickleFile, CloudpickleFile, Sql, BagOfHoldingH5File
from fleche.digest import digest
from fleche.call import Call
try:
    import numpy as np
except ImportError:
    np = None

def benchmark_storage_ops(storage_name, storage_factory, values_to_store, iterations=100):
    results = []

    # Create temp dir for storage
    tmp_dir = tempfile.mkdtemp()
    try:
        storage = storage_factory(tmp_dir)

        # Benchmark Save
        save_times = []
        keys = []
        for i, val in enumerate(values_to_store):
            # We use string keys for simplicity, digest(val) would also work
            try:
                key = digest(val)
                keys.append(key)

                start = time.perf_counter()
                storage.save(val, key)
                end = time.perf_counter()
                save_times.append(end - start)
            except Exception as e:
                print(f"Error saving to {storage_name}: {e}", file=sys.stderr)
                continue

        if save_times:
            results.append({
                "benchmark": "storage_save",
                "storage": storage_name,
                "iterations": len(save_times),
                "avg_time": statistics.mean(save_times),
                "stdev_time": statistics.stdev(save_times) if len(save_times) > 1 else 0,
                "min_time": min(save_times),
                "max_time": max(save_times)
            })

        # Benchmark Load
        load_times = []
        for key in keys:
            try:
                start = time.perf_counter()
                _ = storage.load(key)
                end = time.perf_counter()
                load_times.append(end - start)
            except Exception as e:
                 print(f"Error loading from {storage_name}: {e}", file=sys.stderr)
                 continue

        if load_times:
            results.append({
                "benchmark": "storage_load",
                "storage": storage_name,
                "iterations": len(load_times),
                "avg_time": statistics.mean(load_times),
                "stdev_time": statistics.stdev(load_times) if len(load_times) > 1 else 0,
                "min_time": min(load_times),
                "max_time": max(load_times)
            })

        # Benchmark Evict (if supported, Memory supports it, FileStorage supports it)
        evict_times = []
        for key in keys:
            try:
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
                "avg_time": statistics.mean(evict_times),
                "stdev_time": statistics.stdev(evict_times) if len(evict_times) > 1 else 0,
                "min_time": min(evict_times),
                "max_time": max(evict_times)
            })

    finally:
        shutil.rmtree(tmp_dir)

    return results

def main():
    print("Running Storage Benchmarks...", file=sys.stderr)

    # Test Data
    small_data = [f"value_{i}" for i in range(100)]

    workloads = [("small_strings", small_data)]

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

    try:
         gc.collect()
         # Sql requires a proper SQL URL.
         # And it saves a Call object

         # Note: Sql.save() signature is save(self, call: Call) -> Digest
         # But benchmark_storage_ops calls storage.save(val, key) which is from Storage base class
         # Storage.save(self, value, key) calls self._save(value, key)
         # Sql._save(self, call: Call) -> Digest
         # Wait, Sql inherits from CallStorage which inherits from StorageBase (not Storage)
         # CallStorage.save(self, call: Call) -> Digest
         # So CallStorage.save does not take a key argument in the signature of save, but _save takes call

         # Let's write a wrapper for Sql to adapt it to the interface used in benchmark_storage_ops if we want to reuse it,
         # or just adapt benchmark_storage_ops to handle CallStorage if it detects it.

         # Adapting benchmark_storage_ops is better.
         pass

    except Exception as e:
        print(f"Failed Sql/calls: {e}", file=sys.stderr)

    # Let's do Sql benchmark separately
    sql_results = []
    tmp_dir = tempfile.mkdtemp()
    try:
        storage = Sql(f"sqlite:///{tmp_dir}/db.sqlite")

        save_times = []
        keys = []
        for c in calls_data:
             start = time.perf_counter()
             key = storage.save(c) # CallStorage.save takes only call
             end = time.perf_counter()
             save_times.append(end - start)
             keys.append(key)

        sql_results.append({
            "benchmark": "storage_save",
            "storage": "Sql/calls",
            "iterations": len(save_times),
            "avg_time": statistics.mean(save_times),
            "stdev_time": statistics.stdev(save_times),
            "min_time": min(save_times),
            "max_time": max(save_times)
        })

        load_times = []
        for key in keys:
            start = time.perf_counter()
            _ = storage.load(key)
            end = time.perf_counter()
            load_times.append(end - start)

        sql_results.append({
            "benchmark": "storage_load",
            "storage": "Sql/calls",
            "iterations": len(load_times),
            "avg_time": statistics.mean(load_times),
            "stdev_time": statistics.stdev(load_times),
            "min_time": min(load_times),
            "max_time": max(load_times)
        })

        # Sql supports evict(key)
        evict_times = []
        for key in keys:
            start = time.perf_counter()
            storage.evict(key)
            end = time.perf_counter()
            evict_times.append(end - start)

        sql_results.append({
            "benchmark": "storage_evict",
            "storage": "Sql/calls",
            "iterations": len(evict_times),
            "avg_time": statistics.mean(evict_times),
            "stdev_time": statistics.stdev(evict_times),
            "min_time": min(evict_times),
            "max_time": max(evict_times)
        })

        all_results.extend(sql_results)

    except Exception as e:
        print(f"Failed Sql/calls: {e}", file=sys.stderr)
    finally:
        shutil.rmtree(tmp_dir)

    print(json.dumps(all_results, indent=2))

if __name__ == "__main__":
    main()
