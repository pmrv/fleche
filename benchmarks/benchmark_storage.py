import time
import sys
import json
import shutil
import tempfile
import gc
from dataclasses import dataclass

from fleche.storage import (
    ValueMemory,
    ValuePickleFile,
    ValueBagOfHoldingH5File,
    Sql,
)
from fleche.storage.thread_safe import SerializingMixin
from fleche.digest import digest
from fleche.call import Call
import numpy as np
import timeit
from functools import partial

from utils import st_backend_safe_nested
from hypothesis import given, settings, HealthCheck
from hypothesis.database import InMemoryExampleDatabase


@dataclass(frozen=True)
class ValueMemorySerializing(SerializingMixin, ValueMemory): ...


# PerKeyLockMixin is incompatible with MemoryBackend: the storage dict field
# makes instances unhashable, which WeakKeyDictionary (used by PerKeyLockMixin)
# requires. Only SerializingMixin works here.


def _generate_backend_safe_nested(count=50, max_depth=3, max_size=6):
    """Generate backend-compatible nested test data using hypothesis."""
    collected = []

    @settings(
        max_examples=count,
        suppress_health_check=list(HealthCheck),
        database=InMemoryExampleDatabase(),
    )
    @given(val=st_backend_safe_nested(max_depth=max_depth, max_size=max_size))
    def _collect(val):
        collected.append(val)

    _collect()
    return collected


def benchmark_storage_ops(storage_name, storage_factory, values_to_store):
    results = []

    tmp_dir = tempfile.mkdtemp()
    try:
        storage = storage_factory(tmp_dir)

        keys = [digest(val) for val in values_to_store]
        valid_items = list(zip(values_to_store, keys))

        # Benchmark Save
        save_times = []
        for val, key in valid_items:
            timer = timeit.Timer(partial(storage.save, val, key))
            number = 10
            times = timer.repeat(repeat=3, number=number)
            save_times.extend([t / number for t in times])

        results.append(
            {
                "benchmark": "storage_save",
                "storage": storage_name,
                "iterations": len(valid_items) * 30,
                "time": min(save_times),
            }
        )

        # Benchmark Contains (Hit)
        contains_hit_times = []
        for _, key in valid_items:
            timer = timeit.Timer(partial(storage.contains, key))
            number = 10
            times = timer.repeat(repeat=3, number=number)
            contains_hit_times.extend([t / number for t in times])

        results.append(
            {
                "benchmark": "storage_contains_hit",
                "storage": storage_name,
                "iterations": len(contains_hit_times),
                "time": min(contains_hit_times),
            }
        )

        # Benchmark Contains (Miss)
        contains_miss_times = []
        missing_keys = [digest(f"__missing_key_{i}__") for i in range(len(valid_items))]
        for key in missing_keys:
            timer = timeit.Timer(partial(storage.contains, key))
            number = 10
            times = timer.repeat(repeat=3, number=number)
            contains_miss_times.extend([t / number for t in times])

        results.append(
            {
                "benchmark": "storage_contains_miss",
                "storage": storage_name,
                "iterations": len(contains_miss_times),
                "time": min(contains_miss_times),
            }
        )

        # Benchmark Load
        load_times = []
        for _, key in valid_items:
            timer = timeit.Timer(partial(storage.load, key))
            number = 10
            times = timer.repeat(repeat=3, number=number)
            load_times.extend([t / number for t in times])

        results.append(
            {
                "benchmark": "storage_load",
                "storage": storage_name,
                "iterations": len(load_times),
                "time": min(load_times),
            }
        )

        # Benchmark Evict
        evict_times = []
        for _, key in valid_items:
            # Eviction mutates state, so we can't repeat it via timeit.
            # Measure a single call per key with perf_counter.
            start = time.perf_counter()
            storage.evict(key)
            end = time.perf_counter()
            evict_times.append(end - start)

        results.append(
            {
                "benchmark": "storage_evict",
                "storage": storage_name,
                "iterations": len(evict_times),
                "time": min(evict_times),
            }
        )

    finally:
        shutil.rmtree(tmp_dir)

    return results


def benchmark_sql_ops(storage_label, url, calls_data):
    results = []
    storage = Sql(url)

    # Save
    save_times = []
    keys = []
    for c in calls_data:
        timer = timeit.Timer(partial(storage.save, c))
        number = 10
        times = timer.repeat(repeat=3, number=number)
        save_times.extend([t / number for t in times])
        keys.append(c.to_lookup_key())

    results.append(
        {
            "benchmark": "storage_save",
            "storage": storage_label,
            "iterations": len(calls_data) * 30,
            "time": min(save_times),
        }
    )

    # Contains (Hit)
    contains_hit_times = []
    for key in keys:
        timer = timeit.Timer(partial(storage.contains, key))
        number = 10
        times = timer.repeat(repeat=3, number=number)
        contains_hit_times.extend([t / number for t in times])

    results.append(
        {
            "benchmark": "storage_contains_hit",
            "storage": storage_label,
            "iterations": len(contains_hit_times),
            "time": min(contains_hit_times),
        }
    )

    # Contains (Miss)
    contains_miss_times = []
    missing_keys = [
        Call(
            name="func",
            arguments={"a": f"__missing_{i}__"},
            module="mod",
            version=1,
        ).to_lookup_key()
        for i in range(len(keys))
    ]
    for key in missing_keys:
        timer = timeit.Timer(partial(storage.contains, key))
        number = 10
        times = timer.repeat(repeat=3, number=number)
        contains_miss_times.extend([t / number for t in times])

    results.append(
        {
            "benchmark": "storage_contains_miss",
            "storage": storage_label,
            "iterations": len(contains_miss_times),
            "time": min(contains_miss_times),
        }
    )

    # Load
    load_times = []
    for key in keys:
        timer = timeit.Timer(partial(storage.load, key))
        number = 10
        times = timer.repeat(repeat=3, number=number)
        load_times.extend([t / number for t in times])

    results.append(
        {
            "benchmark": "storage_load",
            "storage": storage_label,
            "iterations": len(keys) * 30,
            "time": min(load_times),
        }
    )

    # Evict (single call per key)
    evict_times = []
    for key in keys:
        start = time.perf_counter()
        storage.evict(key)
        end = time.perf_counter()
        evict_times.append(end - start)

    results.append(
        {
            "benchmark": "storage_evict",
            "storage": storage_label,
            "iterations": len(evict_times),
            "time": min(evict_times),
        }
    )

    return results


def main():
    print("Running Storage Benchmarks...", file=sys.stderr)

    # Test Data
    small_data = [f"value_{i}" for i in range(100)]

    nested_data = _generate_backend_safe_nested()

    workloads = [("small_strings", small_data), ("nested_structures", nested_data)]

    large_data = [np.random.rand(100, 100) for _ in range(20)]
    workloads.append(("numpy_arrays", large_data))

    secret = [b"benchmark-test-key-at-least-32-bytes"]
    factories = {
        "Memory": lambda path: ValueMemory({}),
        "Memory+Locked(Serializing)": lambda path: ValueMemorySerializing({}),
        "PickleFile": lambda path: ValuePickleFile.with_pickle(root=path),
        "PickleFile_Signed": lambda path: ValuePickleFile.with_pickle(
            root=path, secret_key=secret
        ),
        "CloudpickleFile": lambda path: ValuePickleFile.with_cloudpickle(root=path),
        "CloudpickleFile_Signed": lambda path: ValuePickleFile.with_cloudpickle(
            root=path, secret_key=secret
        ),
        "DillFile": lambda path: ValuePickleFile.with_dill(root=path),
        "DillFile_Signed": lambda path: ValuePickleFile.with_dill(
            root=path, secret_key=secret
        ),
        # Sql is a CallStorage, benchmarked separately below
        "BagOfHoldingH5File": lambda path: ValueBagOfHoldingH5File(root=path),
    }

    all_results = []

    for workload_name, data in workloads:
        for storage_name, factory in factories.items():
            gc.collect()
            results = benchmark_storage_ops(
                f"{storage_name}/{workload_name}", factory, data
            )
            all_results.extend(results)

    # Sql specifically with Call objects
    calls_data = [
        Call(name="func", arguments={"a": i}, module="mod", version=1)
        for i in range(50)
    ]

    tmp_dir = tempfile.mkdtemp()
    try:
        for storage_label, url in [
            ("SqlFile/calls", f"sqlite:///{tmp_dir}/db.sqlite"),
            ("SqlMemory/calls", "sqlite:///:memory:"),
        ]:
            gc.collect()
            all_results.extend(benchmark_sql_ops(storage_label, url, calls_data))
    finally:
        shutil.rmtree(tmp_dir)

    print(json.dumps(all_results, indent=2))


if __name__ == "__main__":
    main()
