"""Blake2b vs SHA-256 performance comparison for the fleche digest function.

Run from the benchmarks/ directory:
    python blake2_comparison.py

Generates 4 plots saved to benchmarks/blake2_comparison.png:
  1. Hash cost vs string length
  2. Hash cost vs list length (integer elements)
  3. Hash cost vs numpy array size
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
    """Mirrors fleche.digest._digest_bytes but uses blake2b(digest_size=32).

    digest_size=32 matches SHA-256's 32-byte output, so both functions return
    a 64-character hex string — an equal-sized digest.
    """
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
# Measurement helpers
# ---------------------------------------------------------------------------

REPEAT = 5
MIN_SECONDS = 0.2  # autorange target


def measure(fn, value, *, repeat=REPEAT):
    """Return median µs per call for fn(value)."""
    timer = timeit.Timer(lambda: fn(value))
    n, _ = timer.autorange()
    # autorange can under-shoot for very fast calls; ensure at least MIN_SECONDS
    while True:
        total = sum(timer.repeat(repeat=1, number=n))
        if total >= MIN_SECONDS:
            break
        n *= 2
    times = timer.repeat(repeat=repeat, number=n)
    return sorted(times)[repeat // 2] / n * 1e6  # median µs


# ---------------------------------------------------------------------------
# Input generators
# ---------------------------------------------------------------------------

def make_string(n):
    return "x" * n


def make_list(n):
    return list(range(n))


def make_array(n):
    return np.arange(n, dtype=np.int64)


def make_tree(depth):
    """Build a balanced binary tree of 2-tuples.

    depth=0  → leaf int 0
    depth=1  → (0, 1)
    depth=2  → ((0, 1), (2, 3))
    depth=d  → 2^d leaf integers
    """
    if depth == 0:
        return 0
    left = make_tree(depth - 1)
    right = make_tree(depth - 1)
    return (left, right)


# ---------------------------------------------------------------------------
# Benchmark sweeps
# ---------------------------------------------------------------------------

STRING_SIZES = [10, 50, 100, 500, 1_000, 5_000, 10_000, 50_000, 100_000]
LIST_SIZES   = [1, 5, 10, 50, 100, 500, 1_000, 5_000, 10_000]
ARRAY_SIZES  = [1, 10, 100, 1_000, 10_000, 100_000, 1_000_000]
TREE_DEPTHS  = list(range(1, 14))  # 2 to 8192 leaves


def run_sweep(make_fn, sizes, label):
    sha_times, b2_times = [], []
    for sz in sizes:
        val = make_fn(sz)
        sha_times.append(measure(digest_sha256, val))
        b2_times.append(measure(digest_blake2b, val))
        print(f"  {label}  size={sz:>8d}  sha256={sha_times[-1]:.2f}µs  blake2b={b2_times[-1]:.2f}µs")
    return sha_times, b2_times


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== String sweep ===")
    sha_str,  b2_str  = run_sweep(make_string, STRING_SIZES, "string")
    print("=== List sweep ===")
    sha_list, b2_list = run_sweep(make_list, LIST_SIZES, "list  ")
    print("=== Array sweep ===")
    sha_arr,  b2_arr  = run_sweep(make_array, ARRAY_SIZES, "array ")
    print("=== Tree-depth sweep ===")
    sha_tree, b2_tree = [], []
    for d in TREE_DEPTHS:
        tree = make_tree(d)
        sha_tree.append(measure(digest_sha256, tree))
        b2_tree.append(measure(digest_blake2b, tree))
        print(f"  tree  depth={d:>3d}  sha256={sha_tree[-1]:.2f}µs  blake2b={b2_tree[-1]:.2f}µs")

    # -----------------------------------------------------------------------
    # Plotting
    # -----------------------------------------------------------------------
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    fig.suptitle(
        "SHA-256 vs Blake2b (digest_size=32) — hash cost comparison\n"
        "equal 64-char hex output, same wire format",
        fontsize=13,
    )

    specs = [
        (axes[0, 0], STRING_SIZES, sha_str,  b2_str,  "String length (chars)", "String"),
        (axes[0, 1], LIST_SIZES,   sha_list, b2_list, "List length (int elements)", "List[int]"),
        (axes[1, 0], ARRAY_SIZES,  sha_arr,  b2_arr,  "Array size (int64 elements)", "np.ndarray[int64]"),
    ]

    for ax, xs, sha_t, b2_t, xlabel, title in specs:
        ratio = [s / b for s, b in zip(sha_t, b2_t)]
        ax2 = ax.twinx()
        ax.plot(xs, sha_t,  "o-",  color="tab:blue",   label="SHA-256",  lw=1.8, ms=5)
        ax.plot(xs, b2_t,   "s--", color="tab:orange",  label="Blake2b",  lw=1.8, ms=5)
        ax2.plot(xs, ratio, "^:",  color="tab:green",   label="ratio SHA/B2", lw=1.2, ms=4, alpha=0.7)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel(xlabel)
        ax.set_ylabel("µs per call")
        ax2.set_ylabel("SHA-256 / Blake2b ratio", color="tab:green")
        ax2.tick_params(axis="y", labelcolor="tab:green")
        ax2.axhline(1.0, color="tab:green", lw=0.8, ls="--", alpha=0.4)
        ax.set_title(title)
        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labels1 + labels2, fontsize=8)

    # Tree-depth plot
    ax = axes[1, 1]
    leaves = [2**d for d in TREE_DEPTHS]
    ratio_tree = [s / b for s, b in zip(sha_tree, b2_tree)]
    ax2 = ax.twinx()
    ax.plot(TREE_DEPTHS, sha_tree,  "o-",  color="tab:blue",   label="SHA-256",  lw=1.8, ms=5)
    ax.plot(TREE_DEPTHS, b2_tree,   "s--", color="tab:orange",  label="Blake2b",  lw=1.8, ms=5)
    ax2.plot(TREE_DEPTHS, ratio_tree, "^:", color="tab:green", label="ratio SHA/B2", lw=1.2, ms=4, alpha=0.7)
    ax.set_yscale("log")
    ax.set_xlabel("Tree depth  (2^depth leaves)")
    ax.set_ylabel("µs per call")
    ax2.set_ylabel("SHA-256 / Blake2b ratio", color="tab:green")
    ax2.tick_params(axis="y", labelcolor="tab:green")
    ax2.axhline(1.0, color="tab:green", lw=0.8, ls="--", alpha=0.4)

    # annotate with leaf counts at a few depths
    for d in [4, 8, 12]:
        if d <= TREE_DEPTHS[-1]:
            ax.annotate(
                f"2^{d}={2**d}",
                xy=(d, max(sha_tree[d - 1], b2_tree[d - 1])),
                xytext=(0, 6),
                textcoords="offset points",
                ha="center",
                fontsize=7,
            )

    ax.set_title("Nested 2-tuple tree")
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, fontsize=8)

    plt.tight_layout()
    out = os.path.join(os.path.dirname(__file__), "blake2_comparison.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"\nPlot saved to {out}")


if __name__ == "__main__":
    main()
