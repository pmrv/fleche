"""
Profile which types are digested most frequently across benchmark workloads.

Run from the benchmarks/ directory:
    python profile_digest_types.py

Mirrors the match-arm order in _digest exactly so reported categories map
directly to the case that would be taken.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))
sys.path.insert(0, os.path.dirname(__file__))

import cmath
import dataclasses
import datetime
import numbers
import types
from collections import Counter
from collections.abc import Iterable, Mapping
from numbers import Number

import numpy as np

import fleche.digest as digest_module
from fleche._attrs import is_attrs_instance
from hypothesis import HealthCheck, settings as hyp_settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays as st_arrays
from utils import st_nested_values, generate_examples


# ---------------------------------------------------------------------------
# Categorisation – must mirror the match arms in _digest exactly
# ---------------------------------------------------------------------------

def _categorize(value) -> str:
    """Return the name of the match arm that _digest would take for *value*."""
    # __digest__ protocol check is skipped – we care about the arm taken after it
    if isinstance(value, digest_module.Digest):
        return "Digest"
    if isinstance(value, str):
        return "str"
    if isinstance(value, bytes):
        return "bytes"
    if isinstance(value, int):           # bool is a subclass of int; matches here first
        return "int"
    if isinstance(value, Number):
        return "Number"
    if value is None:
        return "None"
    if isinstance(value, np.bool_):
        return "np.bool_"
    if isinstance(value, np.integer):
        return "np.integer"
    if isinstance(value, np.floating):
        return "np.floating"
    if isinstance(value, np.ndarray):
        return "np.ndarray"
    if isinstance(value, types.FunctionType):
        return "FunctionType"
    if isinstance(value, types.CodeType):
        return "CodeType"
    if isinstance(value, datetime.timezone):
        return "datetime.timezone"
    if isinstance(value, datetime.timedelta):
        return "datetime.timedelta"
    if isinstance(value, datetime.datetime):  # must precede date
        return "datetime.datetime"
    if isinstance(value, datetime.date):
        return "datetime.date"
    if isinstance(value, datetime.time):
        return "datetime.time"
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return "dataclass"
    if is_attrs_instance(value):
        return "attrs"
    if isinstance(value, types.ModuleType):
        return "ModuleType"
    if isinstance(value, Mapping):
        return "Mapping"
    if isinstance(value, Iterable):
        return "Iterable"
    return "Indigestible"


# ---------------------------------------------------------------------------
# Recursive walk – mirrors how _digest recurses
# ---------------------------------------------------------------------------

def _walk(value, counter: Counter) -> None:
    """Walk *value* the same way _digest would recurse, incrementing *counter*."""
    arm = _categorize(value)
    counter[arm] += 1

    # Recurse into sub-values the same way _digest does so we count every call
    if arm == "int":
        pass  # no recursion
    elif arm == "Number":
        if not cmath.isnan(value):
            # _digest calls digest(hash(value)) which is an int
            counter["int"] += 1  # the recursive digest(int) call
    elif arm == "np.bool_":
        counter["int"] += 1
    elif arm == "np.integer":
        counter["int"] += 1
    elif arm == "np.floating":
        # delegates to digest(float(value)) → Number
        counter["Number"] += 1
    elif arm == "np.ndarray":
        counter["str"] += 2   # dtype.str + shape tuple → str
    elif arm == "FunctionType":
        _walk(value.__code__, counter)
    elif arm == "CodeType":
        props = (
            value.co_code, value.co_consts, value.co_names,
            value.co_varnames, value.co_freevars, value.co_cellvars,
            value.co_argcount, value.co_posonlyargcount,
            value.co_kwonlyargcount, value.co_flags,
        )
        _walk(props, counter)
    elif arm == "dataclass":
        fields = {f.name: getattr(value, f.name) for f in dataclasses.fields(value)}
        _walk(fields, counter)
    elif arm == "attrs":
        fields = dict(is_attrs_instance(value) and __import__('fleche._attrs', fromlist=['field_items']).field_items(value) or [])
        _walk(fields, counter)
    elif arm == "Mapping":
        # _digest_mapping calls digest(k) and digest(v) for each item
        for k, v in value.items():
            _walk(k, counter)
            _walk(v, counter)
    elif arm == "Iterable":
        try:
            for v in value:
                _walk(v, counter)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Benchmark workloads
# ---------------------------------------------------------------------------

@hyp_settings(suppress_health_check=[HealthCheck.too_slow])
def _examples(strategy):
    return generate_examples(strategy)


WORKLOADS = {
    "Integer":                   st.integers(),
    "String (len<100)":          st.text(max_size=100),
    "String (len>100)":          st.text(min_size=100),
    "Float":                     st.floats(),
    "None":                      st.none(),
    "List (integers, len<100)":  st.lists(st.integers(), max_size=100),
    "List (integers, len>100)":  st.lists(st.integers(), min_size=100),
    "Dict (small)":              st.dictionaries(
                                     st.text(max_size=10), st.text(max_size=10)
                                 ),
    "Numpy (integers, len<100)": st_arrays(int, st.integers(min_value=0, max_value=100)),
    "Numpy (integers, len>100)": st_arrays(int, st.integers(min_value=100, max_value=10_000)),
    "Nested (Random Hypothesis)": st_nested_values,
}


def main():
    total: Counter = Counter()
    workload_counters: dict[str, Counter] = {}

    for name, strategy in WORKLOADS.items():
        counter: Counter = Counter()
        examples = generate_examples(strategy)
        for ex in examples:
            _walk(ex, counter)
        workload_counters[name] = counter
        total += counter

    # Print per-workload table
    all_arms = sorted(total.keys(), key=lambda k: -total[k])
    header = f"{'Arm':<22}" + "".join(f"{n[:14]:>16}" for n in WORKLOADS) + f"{'TOTAL':>16}"
    print(header)
    print("-" * len(header))
    for arm in all_arms:
        row = f"{arm:<22}"
        for name in WORKLOADS:
            row += f"{workload_counters[name].get(arm, 0):>16}"
        row += f"{total[arm]:>16}"
        print(row)
    print()

    # Proposed order: sort arms by total frequency, respecting constraints
    print("=== Raw frequency ranking (unconstrained) ===")
    for rank, (arm, count) in enumerate(total.most_common(), 1):
        print(f"  {rank:2}. {arm:<22}  {count:>8}")


if __name__ == "__main__":
    main()
