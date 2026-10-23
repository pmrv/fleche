import hashlib

import pytest

import fleche._hashing as _hashing
from fleche._hashing import new_hash, running_hash
from fleche.digest import digest


def test_running_hash_result_is_the_salted_hex_digest():
    with running_hash(b"salt") as h:
        h.update(b"a")
        h.update(b"b")
    expected = new_hash(b"salt")
    expected.update(b"ab")
    assert h.result == expected.hexdigest().encode()


def test_running_hash_result_unavailable_inside_the_block():
    with running_hash(b"salt") as h:
        with pytest.raises(RuntimeError):
            h.result


def test_running_hash_result_unavailable_after_the_block_raises():
    with pytest.raises(ValueError):
        with running_hash(b"salt") as h:
            raise ValueError
    with pytest.raises(RuntimeError):
        h.result


def test_hash_primitive_is_swapped_in_one_place(monkeypatch):
    # The int arm (digest.py) and the number arm (_numbers) both start from
    # _hashing, so one patch there changes every digest.
    before = digest(1), digest(0.5)

    class _Blake2bHashlib:
        @staticmethod
        def sha256():
            return hashlib.blake2b(digest_size=32)

    monkeypatch.setattr(_hashing, "hashlib", _Blake2bHashlib)
    after = digest(1), digest(0.5)
    assert before[0] != after[0]
    assert before[1] != after[1]
