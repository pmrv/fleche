"""Tests that all storages, caches, and their configurations are picklable.

Related issue: https://github.com/pmrv/fleche/issues/207
"""

import pickle
import pytest

from fleche.storage import (
    Memory,
    Void,
    PickleFile,
    DestructuringStorage,
    CallStorageAdapter,
)
from fleche.caches import Cache, ReadOnlyCache, FilteredCache, RefreshingCache, CacheStack
from fleche.call import Call
from fleche.digest import Digest

SECRET_KEY = [b"test_secret_key_32_bytes_long!!!!"]

# A sample Call with digested arguments (no live Python objects in arguments/result)
_SAMPLE_CALL = Call(
    name="test_func",
    arguments={"x": Digest("a" * 64)},
    metadata={},
    module="test_module",
    version=1,
    result=Digest("b" * 64),
)


def roundtrip(obj):
    """Pickle and unpickle an object, returning the restored copy."""
    return pickle.loads(pickle.dumps(obj))


# ---------------------------------------------------------------------------
# Storage picklability
# ---------------------------------------------------------------------------


class TestStoragePickle:
    def test_memory_empty(self):
        mem = Memory({})
        restored = roundtrip(mem)
        assert isinstance(restored, Memory)

    def test_memory_preserves_data(self):
        mem = Memory({})
        key = mem.save(42)
        restored = roundtrip(mem)
        assert restored.load(key) == 42

    def test_void(self):
        void = Void()
        restored = roundtrip(void)
        assert isinstance(restored, Void)

    def test_pickle_file_with_pickle(self, tmp_path):
        store = PickleFile.with_pickle(tmp_path / "store", secret_key=SECRET_KEY)
        key = store.save(42)
        restored = roundtrip(store)
        assert isinstance(restored, PickleFile)
        assert restored.load(key) == 42

    def test_pickle_file_with_cloudpickle(self, tmp_path):
        pytest.importorskip("cloudpickle")
        store = PickleFile.with_cloudpickle(tmp_path / "store", secret_key=SECRET_KEY)
        key = store.save(42)
        restored = roundtrip(store)
        assert isinstance(restored, PickleFile)
        assert restored.load(key) == 42

    def test_pickle_file_with_dill(self, tmp_path):
        pytest.importorskip("dill")
        store = PickleFile.with_dill(tmp_path / "store", secret_key=SECRET_KEY)
        key = store.save(42)
        restored = roundtrip(store)
        assert isinstance(restored, PickleFile)
        assert restored.load(key) == 42

    def test_pickle_file_compress(self, tmp_path):
        store = PickleFile.with_pickle(
            tmp_path / "store", secret_key=SECRET_KEY, compress=True
        )
        key = store.save("hello world")
        restored = roundtrip(store)
        assert restored.load(key) == "hello world"

    def test_pickle_file_no_secret_key(self, tmp_path):
        store = PickleFile.with_pickle(tmp_path / "store", secret_key=[])
        key = store.save(99)
        restored = roundtrip(store)
        assert restored.load(key) == 99

    def test_bag_of_holding_h5_file(self, tmp_path):
        pytest.importorskip("bagofholding")
        from fleche.storage import BagOfHoldingH5File

        store = BagOfHoldingH5File(tmp_path / "h5")
        restored = roundtrip(store)
        assert isinstance(restored, BagOfHoldingH5File)
        # Verify root path is preserved
        assert restored.root == store.root

    def test_sql(self, tmp_path):
        pytest.importorskip("sqlalchemy")
        from fleche.storage import Sql

        store = Sql(str(tmp_path / "calls.db"))
        restored = roundtrip(store)
        assert isinstance(restored, Sql)

    def test_sql_preserves_data(self, tmp_path):
        pytest.importorskip("sqlalchemy")
        from fleche.storage import Sql

        store = Sql(str(tmp_path / "calls.db"))
        key = store.save(_SAMPLE_CALL)
        restored = roundtrip(store)
        loaded = restored.load(key)
        assert loaded.name == _SAMPLE_CALL.name

    def test_sql_in_memory(self):
        pytest.importorskip("sqlalchemy")
        from fleche.storage import Sql

        # in-memory SQLite — data is not preserved across roundtrip but pickling itself must succeed
        store = Sql(None)
        restored = roundtrip(store)
        assert isinstance(restored, Sql)

    def test_destructuring_storage_with_memory(self):
        ds = DestructuringStorage(Memory({}))
        restored = roundtrip(ds)
        assert isinstance(restored, DestructuringStorage)
        key = restored.save([1, 2, 3])
        assert restored.load(key) == [1, 2, 3]

    def test_call_storage_adapter_with_memory(self):
        adapter = CallStorageAdapter(Memory({}))
        restored = roundtrip(adapter)
        assert isinstance(restored, CallStorageAdapter)
        key = restored.save(_SAMPLE_CALL)
        assert restored.load(key) == _SAMPLE_CALL


# ---------------------------------------------------------------------------
# Cache picklability
# ---------------------------------------------------------------------------


def _make_memory_cache():
    return Cache(Memory({}), Memory({}))


def _always_true(call):
    return True


class TestCachePickle:
    def test_cache_with_memory(self):
        cache = _make_memory_cache()
        restored = roundtrip(cache)
        assert isinstance(restored, Cache)

    def test_cache_with_pickle_file(self, tmp_path):
        cache = Cache(
            PickleFile.with_pickle(tmp_path / "values", secret_key=SECRET_KEY),
            PickleFile.with_pickle(tmp_path / "calls", secret_key=SECRET_KEY),
        )
        restored = roundtrip(cache)
        assert isinstance(restored, Cache)

    def test_cache_with_sql_calls_storage(self, tmp_path):
        pytest.importorskip("sqlalchemy")
        from fleche.storage import Sql

        cache = Cache(Memory({}), Sql(str(tmp_path / "calls.db")))
        restored = roundtrip(cache)
        assert isinstance(restored, Cache)

    def test_readonly_cache(self):
        inner = _make_memory_cache()
        ro = ReadOnlyCache(inner)
        restored = roundtrip(ro)
        assert isinstance(restored, ReadOnlyCache)

    def test_filtered_cache_with_named_predicate(self):
        inner = _make_memory_cache()
        fc = FilteredCache(inner, _always_true)
        restored = roundtrip(fc)
        assert isinstance(restored, FilteredCache)

    def test_refreshing_cache(self):
        inner = _make_memory_cache()
        rc = RefreshingCache(inner)
        restored = roundtrip(rc)
        assert isinstance(restored, RefreshingCache)

    def test_cache_stack(self):
        c1 = _make_memory_cache()
        c2 = _make_memory_cache()
        stack = CacheStack((c1, c2))
        restored = roundtrip(stack)
        assert isinstance(restored, CacheStack)
        assert len(restored.stack) == 2

    def test_cache_stack_via_push(self):
        c1 = _make_memory_cache()
        c2 = _make_memory_cache()
        stack = c1.push(c2)
        restored = roundtrip(stack)
        assert isinstance(restored, CacheStack)

    def test_cache_stack_with_mixed_storages(self, tmp_path):
        file_cache = Cache(
            PickleFile.with_pickle(tmp_path / "values", secret_key=SECRET_KEY),
            PickleFile.with_pickle(tmp_path / "calls", secret_key=SECRET_KEY),
        )
        mem_cache = _make_memory_cache()
        stack = CacheStack((mem_cache, file_cache))
        restored = roundtrip(stack)
        assert isinstance(restored, CacheStack)

    def test_readonly_cache_via_method(self):
        inner = _make_memory_cache()
        ro = inner.readonly()
        restored = roundtrip(ro)
        assert isinstance(restored, ReadOnlyCache)

    def test_nested_cache_stack_picklable(self):
        c1 = _make_memory_cache()
        c2 = _make_memory_cache()
        c3 = _make_memory_cache()
        inner_stack = CacheStack((c1, c2))
        # CacheStack.push returns a new stack wrapping inner
        outer = inner_stack.push(c3)
        restored = roundtrip(outer)
        assert isinstance(restored, CacheStack)


# ---------------------------------------------------------------------------
# Functional roundtrip: save before pickling, load after
# ---------------------------------------------------------------------------


class TestPickleFunctionalRoundtrip:
    """Verify that pickled objects remain fully operational."""

    def test_memory_cache_save_then_pickle_then_load(self):
        """Data saved before pickling is accessible after restoring."""
        cache = _make_memory_cache()
        call = Call(
            name="add",
            arguments={"a": 1, "b": 2},
            metadata={},
            module="mymod",
            version=None,
            result=3,
        )
        key = cache.save(call)
        restored = roundtrip(cache)
        loaded = restored.load(key)
        assert loaded.result == 3
        assert loaded.name == "add"

    def test_pickle_file_cache_save_then_pickle_then_load(self, tmp_path):
        cache = Cache(
            PickleFile.with_pickle(tmp_path / "v", secret_key=SECRET_KEY),
            PickleFile.with_pickle(tmp_path / "c", secret_key=SECRET_KEY),
        )
        call = Call(
            name="sub",
            arguments={"x": 10, "y": 3},
            metadata={},
            module=None,
            version=None,
            result=7,
        )
        key = cache.save(call)
        restored = roundtrip(cache)
        loaded = restored.load(key)
        assert loaded.result == 7

    def test_cache_stack_save_to_base_load_after_pickle(self):
        """CacheStack saves to base and loads from either layer after pickling."""
        base = _make_memory_cache()
        upper = _make_memory_cache()
        stack = CacheStack((base, upper))

        call = Call(
            name="mul",
            arguments={"a": 3, "b": 4},
            metadata={},
            module=None,
            version=None,
            result=12,
        )
        stack.save(call)  # saves to base (stack[0])
        key = call.to_lookup_key()

        restored = roundtrip(stack)
        loaded = restored.load(key)
        assert loaded.result == 12

    def test_sql_call_storage_roundtrip_after_pickle(self, tmp_path):
        pytest.importorskip("sqlalchemy")
        from fleche.storage import Sql

        store = Sql(str(tmp_path / "db.sqlite"))
        key = store.save(_SAMPLE_CALL)
        restored = roundtrip(store)
        loaded = restored.load(key)
        assert loaded.name == _SAMPLE_CALL.name
        assert loaded.module == _SAMPLE_CALL.module

    def test_memory_storage_new_saves_after_pickle(self):
        mem = Memory({})
        key1 = mem.save("first")
        restored = roundtrip(mem)
        # can save new values after restore
        key2 = restored.save("second")
        assert restored.load(key1) == "first"
        assert restored.load(key2) == "second"
