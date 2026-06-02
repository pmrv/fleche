"""SHA-256 vs Blake2b vs Blake3 performance comparison for the fleche digest function.

Run from the repo root:
    pip install -e ".[tests]" blake3
    python benchmarks/blake3_comparison.py

Generates 4 plots saved to benchmarks/blake3_comparison.png:
  1. Hash cost vs string size (bytes)
  2. Hash cost vs list size (bytes, treating each int as 8 bytes)
  3. Hash cost vs numpy array size (bytes)
  4. Hash cost vs nested 2-tuple tree depth
"""
import cmath
import hashlib
import numbers
import os
import struct
import sys
import timeit
from collections.abc import Iterable, Mapping
from numbers import Number

import blake3 as _blake3_mod
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from fleche.digest import _digest_bytes, digest as digest_sha256  # noqa: E402


# ---------------------------------------------------------------------------
# Blake2b drop-in — identical wire format, only the hash primitive differs
# ---------------------------------------------------------------------------

def _blake2b_bytes(value):
    """Mirrors fleche.digest._digest_bytes but uses blake2b(digest_size=32)."""
    m = hashlib.blake2b(digest_size=32)
    t = type(value)
    m.update(t.__name__.encode())
    match value:
        case int():
            m.update(
                value.to_bytes(
                    (value.bit_length() + 8) // 8, byteorder="little", signed=True
                )
            )
        case str():
            m.update(value.encode())
        case None:
            m.update(b"__None__")
        case Number():
            if cmath.isnan(value):
                if isinstance(value, numbers.Complex):
                    m.update(struct.pack("<dd", value.real, value.imag))
                else:
                    m.update(struct.pack("<d", value))
            else:
                return _blake2b_bytes(hash(value))
        case bytes():
            m.update(value)
        case np.ndarray():
            m.update(_blake2b_bytes(value.dtype.str))
            m.update(_blake2b_bytes(value.shape))
            m.update(value.tobytes())
        case Mapping():
            sorted_items = sorted(
                ((_blake2b_bytes(k), k, v) for k, v in value.items()),
                key=lambda item: item[0],
            )
            for k_bytes, k, v in sorted_items:
                m.update(k_bytes)
                m.update(_blake2b_bytes(v))
        case Iterable():
            for v in value:
                m.update(_blake2b_bytes(v))
        case _:
            raise ValueError(f"Cannot digest {type(value)}")
    return m.hexdigest().encode()


def digest_blake2b(value):
    return _blake2b_bytes(value).decode()


# ---------------------------------------------------------------------------
# Blake3 drop-in
# ---------------------------------------------------------------------------

def _blake3_bytes(value):
    """Mirrors fleche.digest._digest_bytes but uses blake3."""
    m = _blake3_mod.blake3()
    t = type(value)
    m.update(t.__name__.encode())
    match value:
        case int():
            m.update(
                value.to_bytes(
                    (value.bit_length() + 8) // 8, byteorder="little", signed=True
                )
            )
        case str():
            m.update(value.encode())
        case None:
            m.update(b"__None__")
        case Number():
            if cmath.isnan(value):
                if isinstance(value, numbers.Complex):
                    m.update(struct.pack("<dd", value.real, value.imag))
                else:
                    m.update(struct.pack("<d", value))
            else:
                return _blake3_bytes(hash(value))
        case bytes():
            m.update(value)
        case np.ndarray():
            m.update(_blake3_bytes(value.dtype.str))
            m.update(_blake3_bytes(value.shape))
            m.update(value.tobytes())
        case Mapping():
            sorted_items = sorted(
                ((_blake3_bytes(k), k, v) for k, v in value.items()),
                key=lambda item: item[0],
            )
            for k_bytes, k, v in sorted_items:
                m.update(k_bytes)
                m.update(_blake3_bytes(v))
        case Iterable():
            for v in value:
                m.update(_blake3_bytes(v))
        case _:
            raise ValueError(f"Cannot digest {type(value)}")
    return m.hexdigest().encode()


def digest_blake3(value):
    return _blake3_bytes(value).decode()


# ---------------------------------------------------------------------------
# Measurement helpers
# ---------------------------------------------------------------------------

REPEAT = 5
MIN_SECONDS = 0.2


def measure(fn, value, *, repeat=REPEAT):
    """Return median µs per call for fn(value)."""
    timer = timeit.Timer(lambda: fn(value))
    n, _ = timer.autorange()
    while True:
        total = sum(timer.repeat(repeat=1, number=n))
        if total >= MIN_SECONDS:
            break
        n *= 2
    times = timer.repeat(repeat=repeat, number=n)
    return sorted(times)[repeat // 2] / n * 1e6  # median µs


# ---------------------------------------------------------------------------
# Input sizes — element counts; converted to total bytes for x-axis labels
#
# String:  1 byte per ASCII char  → bytes = n
# List:    8 bytes per int (int64 approximation) → bytes = n * 8
# Array:   8 bytes per int64 element → bytes = n * 8
# ---------------------------------------------------------------------------

STRING_NS = [10, 50, 100, 500, 1_000, 5_000, 10_000, 50_000, 100_000]
LIST_NS   = [1, 5, 10, 50, 100, 500, 1_000, 5_000, 10_000]
ARRAY_NS  = [1, 10, 100, 1_000, 10_000, 100_000, 1_000_000]
TREE_DEPTHS = list(range(1, 14))

STRING_BYTES = STRING_NS                    # 1 byte per ASCII char
LIST_BYTES   = [n * 8 for n in LIST_NS]    # 8 bytes per int (int64)
ARRAY_BYTES  = [n * 8 for n in ARRAY_NS]   # 8 bytes per int64


def make_string(n):
    return "x" * n


def make_list(n):
    return list(range(n))


def make_array(n):
    return np.arange(n, dtype=np.int64)


def make_tree(depth):
    """Balanced binary tree of 2-tuples; depth=0 is leaf int 0."""
    if depth == 0:
        return 0
    left = make_tree(depth - 1)
    right = make_tree(depth - 1)
    return (left, right)


# ---------------------------------------------------------------------------
# Benchmark sweeps
# ---------------------------------------------------------------------------

def run_sweep(make_fn, ns, label):
    sha_times, b2_times, b3_times = [], [], []
    for n in ns:
        val = make_fn(n)
        sha_times.append(measure(digest_sha256, val))
        b2_times.append(measure(digest_blake2b, val))
        b3_times.append(measure(digest_blake3, val))
        print(
            f"  {label}  n={n:>8d}  sha256={sha_times[-1]:.2f}µs  "
            f"blake2b={b2_times[-1]:.2f}µs  blake3={b3_times[-1]:.2f}µs"
        )
    return sha_times, b2_times, b3_times


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== String sweep ===")
    sha_str,  b2_str,  b3_str  = run_sweep(make_string, STRING_NS, "string")
    print("=== List sweep ===")
    sha_list, b2_list, b3_list = run_sweep(make_list,   LIST_NS,   "list  ")
    print("=== Array sweep ===")
    sha_arr,  b2_arr,  b3_arr  = run_sweep(make_array,  ARRAY_NS,  "array ")
    print("=== Tree-depth sweep ===")
    sha_tree, b2_tree, b3_tree = [], [], []
    for d in TREE_DEPTHS:
        tree = make_tree(d)
        sha_tree.append(measure(digest_sha256, tree))
        b2_tree.append(measure(digest_blake2b, tree))
        b3_tree.append(measure(digest_blake3, tree))
        print(
            f"  tree  depth={d:>3d}  sha256={sha_tree[-1]:.2f}µs  "
            f"blake2b={b2_tree[-1]:.2f}µs  blake3={b3_tree[-1]:.2f}µs"
        )

    # -----------------------------------------------------------------------
    # Plotting
    # -----------------------------------------------------------------------
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    fig.suptitle(
        "SHA-256 vs Blake2b (digest_size=32) vs Blake3 — hash cost comparison\n"
        "equal 64-char hex output, same wire format",
        fontsize=13,
    )

    specs = [
        (axes[0, 0], STRING_BYTES, sha_str,  b2_str,  b3_str,  "Input size (bytes)", "String"),
        (axes[0, 1], LIST_BYTES,   sha_list, b2_list, b3_list, "Input size (bytes, 8 bytes/int)", "List[int]"),
        (axes[1, 0], ARRAY_BYTES,  sha_arr,  b2_arr,  b3_arr,  "Input size (bytes)", "np.ndarray[int64]"),
    ]

    for ax, xs, sha_t, b2_t, b3_t, xlabel, title in specs:
        ax.plot(xs, sha_t, "o-",  color="tab:blue",   label="SHA-256",  lw=1.8, ms=5)
        ax.plot(xs, b2_t,  "s--", color="tab:orange", label="Blake2b",  lw=1.8, ms=5)
        ax.plot(xs, b3_t,  "^:",  color="tab:red",    label="Blake3",   lw=1.8, ms=5)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel(xlabel)
        ax.set_ylabel("µs per call")
        ax.set_title(title)
        ax.legend(fontsize=8)
        ax.grid(True, which="both", alpha=0.3)

    # Tree-depth plot (x-axis is depth, not bytes)
    ax = axes[1, 1]
    ax.plot(TREE_DEPTHS, sha_tree, "o-",  color="tab:blue",   label="SHA-256",  lw=1.8, ms=5)
    ax.plot(TREE_DEPTHS, b2_tree,  "s--", color="tab:orange", label="Blake2b",  lw=1.8, ms=5)
    ax.plot(TREE_DEPTHS, b3_tree,  "^:",  color="tab:red",    label="Blake3",   lw=1.8, ms=5)
    ax.set_yscale("log")
    ax.set_xlabel("Tree depth  (2^depth leaves)")
    ax.set_ylabel("µs per call")
    ax.set_title("Nested 2-tuple tree")
    for d in [4, 8, 12]:
        if d <= TREE_DEPTHS[-1]:
            max_t = max(sha_tree[d - 1], b2_tree[d - 1], b3_tree[d - 1])
            ax.annotate(
                f"2^{d}={2**d}",
                xy=(d, max_t),
                xytext=(0, 6),
                textcoords="offset points",
                ha="center",
                fontsize=7,
            )
    ax.legend(fontsize=8)
    ax.grid(True, which="both", alpha=0.3)

    plt.tight_layout()
    out = os.path.join(os.path.dirname(__file__), "blake3_comparison.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"\nPlot saved to {out}")


if __name__ == "__main__":
    main()
