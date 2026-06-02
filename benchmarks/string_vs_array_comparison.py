"""Overlay string vs numpy-array hashing at equal byte sizes.

Both are 'bulk bytes hashing' workloads — this plot puts them on the same
x/y axes so their curves can be compared directly.

Run from the repo root:
    pip install -e ".[tests]" blake3
    python benchmarks/string_vs_array_comparison.py
"""
import cmath
import hashlib
import numbers
import os
import struct
import sys
import timeit

import blake3 as _blake3_mod
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from fleche.digest import digest as digest_sha256  # noqa: E402


# ---------------------------------------------------------------------------
# Drop-in replacements (blake2b / blake3)
# ---------------------------------------------------------------------------

def _hash_bytes(value, new_hash):
    m = new_hash()
    t = type(value)
    m.update(t.__name__.encode())
    match value:
        case int():
            m.update(value.to_bytes((value.bit_length() + 8) // 8, "little", signed=True))
        case str():
            m.update(value.encode())
        case np.ndarray():
            m.update(_hash_bytes(value.dtype.str, new_hash))
            m.update(_hash_bytes(value.shape, new_hash))
            m.update(value.tobytes())
        case tuple():
            for v in value:
                m.update(_hash_bytes(v, new_hash))
        case _:
            raise ValueError(type(value))
    return m.hexdigest().encode() if hasattr(m, "hexdigest") else m.digest()


def make_sha256():  return hashlib.sha256()
def make_blake2b(): return hashlib.blake2b(digest_size=32)
def make_blake3():  return _blake3_mod.blake3()

HASHERS = [
    ("SHA-256", make_sha256,  "tab:blue",   "o-"),
    ("Blake2b", make_blake2b, "tab:orange", "s--"),
    ("Blake3",  make_blake3,  "tab:red",    "^:"),
]


# ---------------------------------------------------------------------------
# Shared byte sizes — identical x-axis for string and array
# ---------------------------------------------------------------------------

# 8 bytes to 8 MB in log steps
BYTE_SIZES = [8, 80, 800, 8_000, 80_000, 800_000, 8_000_000]

REPEAT = 5
MIN_SECONDS = 0.1


def measure(fn, value, repeat=REPEAT):
    timer = timeit.Timer(lambda: fn(value))
    n, _ = timer.autorange()
    while True:
        if sum(timer.repeat(repeat=1, number=n)) >= MIN_SECONDS:
            break
        n *= 2
    times = timer.repeat(repeat=repeat, number=n)
    return sorted(times)[repeat // 2] / n * 1e6  # median µs


def run(make_value, label):
    results = {}
    for name, new_hash, _, _ in HASHERS:
        times = []
        for b in BYTE_SIZES:
            val = make_value(b)
            fn = lambda v=val, h=new_hash: _hash_bytes(v, h)
            t = measure(fn, val)
            times.append(t)
            print(f"  {label:6s}  {name:7s}  {b:>10d} bytes  {t:.2f} µs")
        results[name] = times
    return results


def make_string(n_bytes):
    return "x" * n_bytes


def make_array(n_bytes):
    return np.zeros(n_bytes // 8, dtype=np.int64)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== String sweep (1 byte per char) ===")
    str_results = run(make_string, "string")

    print("=== Array sweep (int64, 8 bytes per element) ===")
    arr_results = run(make_array, "array")

    # -----------------------------------------------------------------------
    # Plot: one panel per hash function, string vs array overlaid
    # -----------------------------------------------------------------------
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=True)
    fig.suptitle(
        "String vs np.ndarray — same total bytes, same axes\n"
        "(bulk-bytes regime: are they identical?)",
        fontsize=12,
    )

    for ax, (name, _, color, _) in zip(axes, HASHERS):
        ax.plot(BYTE_SIZES, str_results[name], "o-",  color=color,   label="str",      lw=2, ms=6)
        ax.plot(BYTE_SIZES, arr_results[name], "s--", color="black", label="ndarray", lw=2, ms=6, alpha=0.7)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("Total input bytes")
        ax.set_ylabel("µs per call")
        ax.set_title(name)
        ax.legend(fontsize=9)
        ax.grid(True, which="both", alpha=0.3)

    plt.tight_layout()
    out = os.path.join(os.path.dirname(__file__), "string_vs_array.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"\nPlot saved to {out}")

    # -----------------------------------------------------------------------
    # Print ratio table
    # -----------------------------------------------------------------------
    print("\n=== array / string cost ratio (>1 means array is slower) ===")
    print(f"{'bytes':>12s}", end="")
    for name, _, _, _ in HASHERS:
        print(f"  {name:>10s}", end="")
    print()
    for i, b in enumerate(BYTE_SIZES):
        print(f"{b:>12d}", end="")
        for name, _, _, _ in HASHERS:
            ratio = arr_results[name][i] / str_results[name][i]
            print(f"  {ratio:>10.2f}x", end="")
        print()


if __name__ == "__main__":
    main()
