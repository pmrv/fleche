"""Path arguments are keyed as passed (two-phase save + content addressing).

A function that writes into a directory it received used to be recorded under
the post-mutation tree and could never hit; with the two-phase save protocol
the identity is sealed before the body runs.  See
docs/usage/file_semantics.rst, "Argument mutation".
"""
from pathlib import Path

import fleche as fl
from fleche import fleche


def make_input(root: Path, name: str) -> Path:
    d = root / name / "data"
    d.mkdir(parents=True)
    (d / "in.txt").write_text("same content")
    return d


def test_mutating_path_consumer_hits(tmp_path):
    with fl.cache("memory"):
        runs = []

        @fleche
        def consume(d: Path):
            runs.append(1)
            (d / "out.txt").write_text("produced")
            return sorted(p.name for p in d.iterdir())

        assert consume(make_input(tmp_path, "a")) == ["in.txt", "out.txt"]
        d2 = make_input(tmp_path, "b")           # identical tree, as passed
        assert consume(d2) == ["in.txt", "out.txt"]
        assert len(runs) == 1                    # keyed on the pre-call tree: hit
        assert not (d2 / "out.txt").exists()     # the mutation is not replayed


def test_mutated_state_is_a_different_call(tmp_path):
    with fl.cache("memory"):
        runs = []

        @fleche
        def consume(d: Path):
            runs.append(1)
            (d / "out.txt").write_text("produced")
            return len(list(d.iterdir()))

        d1 = make_input(tmp_path, "a")
        consume(d1)                              # cold; d1 now holds in+out
        consume(d1)                              # post-mutation tree: honest miss,
        assert len(runs) == 2                    # not a false hit on the old record


def test_returned_mutated_argument_captured_in_final_state(tmp_path):
    with fl.cache("memory"):
        runs = []

        @fleche
        def stamp(d: Path) -> Path:
            runs.append(1)
            (d / "stamp.txt").write_text("stamped")
            return d

        stamp(make_input(tmp_path, "a"))
        warm = stamp(make_input(tmp_path, "b"))  # hit, keyed on the input as passed
        assert len(runs) == 1
        # ... but the result was captured at commit time: final, stamped state.
        assert sorted(p.name for p in warm.iterdir()) == ["in.txt", "stamp.txt"]
        assert (warm / "stamp.txt").read_text() == "stamped"
