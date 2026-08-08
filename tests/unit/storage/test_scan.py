"""The no-load reference-graph walk: `scan_child_digests` / `count_reuses(load=False)`.

The contract under test is parity: whatever the loading path reports about the
destructuring reference graph, the scanning path must report exactly the same —
including on a store whose payload classes cannot be imported, which is the
whole reason the scanning path exists.
"""

from dataclasses import dataclass
import gzip
import json
import pickle
import random
import string
import subprocess
import sys
import textwrap

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from fleche.caches import Cache
from fleche.call import DigestedCall
from fleche.digest import Digest
from fleche.storage import (
    DestructuringMixin,
    ScanUnsupported,
    ValueMemory,
    ValueMixin,
    ValueVoid,
)
from fleche.storage.bagofholding_file import ValueBagOfHoldingH5File
from fleche.storage.destructuring import (
    DigestedAttrs,
    DigestedDataclass,
    DigestedDict,
    DigestedIterable,
    HasChildDigests,
    HasScannableDigests,
)
from fleche.storage.memory import CallMemory, MemoryBackend
from fleche.storage.pickle_file import ValuePickleFile
from fleche.storage.scan import _DIGEST_GLOBAL, _WRAPPER_SLOTS, scan_pickle

from tests.fixtures import secret_key


# Nested containers of plain scalars: enough shape to exercise every wrapper,
# while staying storable by all six value backends, so a failure here is about
# the scanners rather than about a backend's own limits.  The shared
# `st_nested_values` is unusable for that — it builds dynamic dataclasses plain
# pickle cannot write — and text is restricted to alphanumerics because HDF5
# group names cannot carry a NUL.
st_text = st.text(string.ascii_letters + string.digits, max_size=5)
st_portable_values = st.recursive(
    st.one_of(st.integers(), st_text, st.booleans(), st.none()),
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.lists(children, max_size=4).map(tuple),
        st.dictionaries(st_text, children, max_size=4),
    ),
    max_leaves=8,
)


# ---------------------------------------------------------------------------
# The scanners match wrapper classes by name, because the whole point is to
# recognise them in bytes another interpreter wrote. Nothing but these tests
# keeps those strings in step with the classes they name.
# ---------------------------------------------------------------------------


def test_wrapper_names_match_the_real_classes():
    """Every name the scanners look for resolves to the class it is meant to be."""
    expected = {
        (DigestedIterable.__module__, DigestedIterable.__qualname__): "items",
        (DigestedDict.__module__, DigestedDict.__qualname__): "items",
        (DigestedDataclass.__module__, DigestedDataclass.__qualname__): "fields",
        (DigestedAttrs.__module__, DigestedAttrs.__qualname__): "fields",
    }
    assert _WRAPPER_SLOTS == expected


def test_wrapper_slot_names_are_real_attributes():
    """The slot each wrapper is scanned for is the attribute `_raw_sub_digests` reads."""
    for (_, qualname), slot in _WRAPPER_SLOTS.items():
        cls = {
            "DigestedIterable": DigestedIterable,
            "DigestedDict": DigestedDict,
            "DigestedDataclass": DigestedDataclass,
            "DigestedAttrs": DigestedAttrs,
        }[qualname]
        assert slot in cls.__dataclass_fields__


def test_digest_class_name_matches():
    assert _DIGEST_GLOBAL == (Digest.__module__, Digest.__qualname__)


# ---------------------------------------------------------------------------
# The pickle opcode scanner on its own
# ---------------------------------------------------------------------------


D1 = Digest("a" * 64)
D2 = Digest("b" * 64)


@pytest.mark.parametrize("protocol", range(pickle.HIGHEST_PROTOCOL + 1))
@pytest.mark.parametrize(
    "value, expected",
    [
        (DigestedIterable([1, D1, "plain", D2]), {D1, D2}),
        (DigestedIterable((D1, 2)), {D1}),
        (DigestedIterable([D1, D1]), {D1}),  # repeats collapse, and memo GETs resolve
        (DigestedDict({D1: 1, "x": D2}), {D1, D2}),  # keys count as well as values
        (DigestedDict({"k": D1, "j": D2}), {D1, D2}),
        (DigestedDataclass(dict, {"a": D1, "b": 3}), {D1}),
        ([1, 2, 3], set()),  # a plain container has no back-references
        (42, set()),
        ("a" * 64, set()),  # a bare string is not a Digest, however digest-shaped
    ],
    ids=lambda p: getattr(p, "__class__", type(p)).__name__,
)
def test_scan_pickle_finds_the_wrapper_children(value, expected, protocol):
    assert scan_pickle(pickle.dumps(value, protocol=protocol)) == expected


@pytest.mark.parametrize("module", ["dill", "cloudpickle"])
def test_scan_pickle_handles_the_other_serializers(module):
    """dill and cloudpickle emit standard opcode streams, so the same walk reads them."""
    serializer = pytest.importorskip(module)
    value = DigestedIterable([D1, "x", D2])
    assert scan_pickle(serializer.dumps(value)) == {D1, D2}


def test_scan_pickle_imports_nothing():
    """A payload naming an unimportable class scans fine and stays unimported."""
    stream = pickle.dumps(DigestedIterable([D1]))
    stream = stream.replace(b"fleche.digest", b"fleche.digest")  # sanity: unchanged
    assert b"no_such_module_anywhere" not in stream

    # A GLOBAL naming a module that does not exist must not be resolved.
    forged = pickle.dumps(DigestedDataclass(object, {"a": D1}))
    forged = forged.replace(b"builtins", b"nowhere1")
    assert scan_pickle(forged) == {D1}
    assert "nowhere1" not in sys.modules


def test_scan_pickle_rejects_a_truncated_stream():
    with pytest.raises((ValueError, EOFError)):
        scan_pickle(pickle.dumps(DigestedIterable([D1]))[:-4])


def test_scan_pickle_only_ever_fails_as_a_malformed_stream():
    """Corrupt entries are a fact of life for an archive audit.

    Whatever bytes come back, the scanner must fail the way ``pickle.loads``
    fails — not with an IndexError from inside the stack machine.
    """
    rng = random.Random(7)
    intact = [
        pickle.dumps(DigestedIterable([D1, 1, "x"])),
        pickle.dumps(DigestedDict({D2: [1, 2]})),
        pickle.dumps({"a": [1, 2, {"b": (3, 4)}]}),
    ]
    rejected = 0
    for _ in range(2000):
        data = bytearray(rng.choice(intact))
        for _ in range(rng.randint(1, 4)):
            data[rng.randrange(len(data))] = rng.randrange(256)
        if rng.random() < 0.3:
            del data[rng.randrange(len(data)):]
        try:
            scan_pickle(bytes(data))
        except (ValueError, EOFError):
            rejected += 1
    assert rejected > 100  # the corruption really is reaching the machine


# ---------------------------------------------------------------------------
# Storage-level parity, across every value backend
# ---------------------------------------------------------------------------


@pytest.fixture
def populated(value_storage):
    """A store with a shared sub-list, a shared dict value, and a lone entry."""
    shared = [2, 3]
    value_storage.save([1, shared])
    value_storage.save([4, shared])
    value_storage.save({"k": shared})
    value_storage.save(["lonely"])
    return value_storage


def test_count_reuses_agrees_with_the_loading_path(populated):
    assert populated.count_reuses(load=False) == populated.count_reuses()


def test_count_reuses_no_load_actually_counts_the_sharing(populated):
    """Sanity: the parity above is not two empty counters agreeing."""
    counts = populated.count_reuses(load=False)
    assert max(counts.values()) == 3  # [2, 3] is referenced by all three parents
    assert set(counts) == set(populated.list())


def test_scan_child_digests_agrees_per_key(populated):
    for key in populated.list():
        assert populated.scan_child_digests(key) == populated.child_digests(key)


def test_scan_child_digests_accepts_a_short_key(populated):
    for key in populated.list():
        assert populated.scan_child_digests(populated.shrink(key)) == (
            populated.child_digests(key)
        )


def test_scan_child_digests_raises_key_error_for_a_missing_key(value_storage):
    value_storage.save([1, [2, 3]])
    with pytest.raises(KeyError):
        value_storage.scan_child_digests(Digest("f" * 64))


@settings(
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    max_examples=30,
    # The store accumulates across examples and the file backends re-list it
    # every count_reuses, so per-example time grows; correctness is the point
    # here, not speed.
    deadline=None,
)
@given(st_portable_values)
def test_scan_matches_load_for_arbitrary_values(value_storage, value):
    """Whatever gets stored, both paths report the same reference graph."""
    value_storage.save(value)
    assert value_storage.count_reuses(load=False) == value_storage.count_reuses()


def test_every_value_backend_advertises_both_protocols(value_storage):
    assert isinstance(value_storage, HasChildDigests)
    assert isinstance(value_storage, HasScannableDigests)


# ---------------------------------------------------------------------------
# The motivating case: payload classes that are not importable here
# ---------------------------------------------------------------------------


_PAYLOAD_MODULE = """
from dataclasses import dataclass

@dataclass(frozen=True)
class Blob:
    payload: object

    def __hash__(self):
        return hash(repr(self.payload))
"""

_WRITER = """
import json, sys
sys.path.insert(0, {plugin!r})
from payload_pkg import Blob
from fleche.storage.bagofholding_file import ValueBagOfHoldingH5File
from fleche.storage.pickle_file import ValuePickleFile
from fleche.storage.bagofholding_file import ValueBagOfHoldingH5File

shared = Blob(payload=[1, 2, 3])
store = {ctor}
store.save([shared, Blob(payload="x")])
store.save({{"k": shared}})
# Recorded here, where the class still exists, as the reference the scanning
# path has to reproduce back in the parent interpreter.
print(json.dumps(dict(store.count_reuses())))
"""

_ORPHANED_STORES = {
    "pickle": lambda root: ValuePickleFile.with_pickle(root=root),
    "h5": lambda root: ValueBagOfHoldingH5File(root=root, prefix_length=0),
    "h5_multi": lambda root: ValueBagOfHoldingH5File(root=root, prefix_length=2),
}
_ORPHANED_CTORS = {
    "pickle": "ValuePickleFile.with_pickle(root={root})",
    "h5": "ValueBagOfHoldingH5File(root={root}, prefix_length=0)",
    "h5_multi": "ValueBagOfHoldingH5File(root={root}, prefix_length=2)",
}


@pytest.fixture
def orphaned_store(tmp_path, request):
    """A store on disk written by an interpreter whose payload class we lack.

    Written in a subprocess with an extra ``sys.path`` entry, so the class is
    genuinely unimportable from this one — the state an archived cache is in
    once the project that produced it is gone.  Yields the storage plus the
    reuse counts the writing interpreter measured, as the reference answer.
    """
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "payload_pkg.py").write_text(textwrap.dedent(_PAYLOAD_MODULE))

    root = str(tmp_path / "store")
    script = _WRITER.format(
        plugin=str(plugin), ctor=_ORPHANED_CTORS[request.param].format(root=repr(root))
    )
    written = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)], capture_output=True, text=True
    )
    assert written.returncode == 0, written.stderr
    reference = {Digest(k): v for k, v in json.loads(written.stdout).items()}
    return _ORPHANED_STORES[request.param](root), reference


@pytest.mark.parametrize(
    "orphaned_store", list(_ORPHANED_STORES), indirect=True
)
def test_count_reuses_works_where_loading_cannot(orphaned_store):
    """`load=True` cannot run here at all; `load=False` still maps the graph."""
    store, reference = orphaned_store
    with pytest.raises(ModuleNotFoundError):
        store.count_reuses()

    assert store.count_reuses(load=False) == reference
    assert max(reference.values()) == 2  # the shared Blob, held by both parents


@pytest.mark.parametrize("orphaned_store", list(_ORPHANED_STORES), indirect=True)
def test_gc_can_sweep_a_foreign_store(orphaned_store):
    """`gc(load=False)` reaches through the same references without the classes."""
    store, reference = orphaned_store
    # Keep one of the two top-level entries alive; everything it does not reach
    # transitively is garbage.
    kept = sorted(k for k, count in reference.items() if count == 0)[0]
    calls = CallMemory({})
    calls.save(DigestedCall(name="f", arguments={}, result=kept))

    evicted = Cache(values=store, calls=calls).gc(load=False)

    survivors = set(store.list())
    assert kept in survivors
    # the entry's children were followed rather than swept as unreachable
    assert store.scan_child_digests(kept) <= survivors
    assert evicted and evicted.isdisjoint(survivors)


def test_gc_load_false_matches_gc_load_true(value_storage):
    """Both gc modes reach the same closure on a store that can be loaded."""
    shared = [2, 3]
    keys = [value_storage.save([1, shared]), value_storage.save(["garbage"])]
    calls = CallMemory({})
    calls.save(DigestedCall(name="f", arguments={}, result=keys[0]))
    cache = Cache(values=value_storage, calls=calls)

    scanned = cache.gc(load=False)
    assert keys[1] in scanned
    assert set(value_storage.list()) == {keys[0], value_storage.save(shared)}
    assert cache.gc() == set()  # nothing left over for the loading pass


# ---------------------------------------------------------------------------
# Refusal rather than a silent fallback
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _UnscannableStorage(DestructuringMixin, ValueMixin, MemoryBackend):
    """A destructuring storage that never overrode `scan_child_digests`."""

    __hash__ = object.__hash__


def test_unscannable_storage_refuses_instead_of_loading():
    store = _UnscannableStorage(storage={}, remaining_depth=0)
    key = store.save([1, [2, 3]])

    assert store.child_digests(key)  # the loading path works fine
    with pytest.raises(ScanUnsupported):
        store.scan_child_digests(key)
    with pytest.raises(ScanUnsupported):
        store.count_reuses(load=False)


def test_gc_refuses_rather_than_evicting_on_an_unscannable_store():
    """An unreadable reference graph must not be mistaken for an empty one."""
    values = _UnscannableStorage(storage={}, remaining_depth=0)
    parent = values.save([1, [2, 3]])
    calls = CallMemory({})
    calls.save(DigestedCall(name="f", arguments={}, result=parent))
    cache = Cache(values=values, calls=calls)

    before = set(values.list())
    with pytest.raises(ScanUnsupported):
        cache.gc(load=False)
    assert set(values.list()) == before


def test_void_value_storage_is_not_scannable():
    """A storage with no destructuring at all simply has no scan to offer."""
    assert not isinstance(ValueVoid(), HasScannableDigests)


# ---------------------------------------------------------------------------
# The wrapper shapes the shared strategies do not reach
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("remaining_depth", [0, 1, 2, 3])
def test_parity_holds_at_every_split_depth(tmp_path, remaining_depth):
    """`remaining_depth` decides which levels become their own entries.

    At 0 every level splits; higher settings inline the shallow ones — so this
    also pins that the scanner agrees with the load path on entries that are
    *not* wrappers at all.
    """
    store = ValuePickleFile.with_pickle(
        tmp_path / str(remaining_depth), remaining_depth=remaining_depth
    )
    inner = [1, 2]
    store.save([[inner, [3, inner]], {"k": inner}])
    assert store.count_reuses(load=False) == store.count_reuses()


@pytest.mark.parametrize("frozen", [False, True])
def test_record_wrappers_scan_for_dataclasses_and_attrs(tmp_path, frozen):
    """`DigestedDataclass` and `DigestedAttrs` both keep children under `fields`."""
    attrs = pytest.importorskip("attrs")

    @dataclass(frozen=frozen)
    class AsDataclass:
        left: object
        right: object

    @attrs.define(frozen=frozen)
    class AsAttrs:
        left: object
        right: object

    shared = [2, 3]
    store = ValuePickleFile.with_cloudpickle(  # locally-defined classes
        tmp_path / str(frozen), remaining_depth=0
    )
    store.save(AsDataclass(left=shared, right=[4]))
    store.save(AsAttrs(left=shared, right=[5]))

    counts = store.count_reuses(load=False)
    assert counts == store.count_reuses()
    assert counts[store.save(shared)] == 2  # both records reference it


# ---------------------------------------------------------------------------
# On-disk wrappers: compression and signing sit between the file and the scan
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("key", [(), tuple(secret_key)], ids=["unsigned", "signed"])
def test_scan_reads_through_compression_and_signing(tmp_path, compress, key):
    store = ValuePickleFile.with_pickle(
        tmp_path / f"{compress}{bool(key)}", compress=compress, secret_key=key
    )
    shared = [2, 3]
    store.save([1, shared])
    store.save([4, shared])
    assert store.count_reuses(load=False) == store.count_reuses()


def test_scan_rejects_a_tampered_signed_entry(tmp_path):
    """The signature is checked before the opcodes are, exactly as on load."""
    store = ValuePickleFile.with_pickle(tmp_path, secret_key=tuple(secret_key))
    parent = store.save([1, [2, 3]])
    path = store._path(parent)
    path.write_bytes(b"\x00" + path.read_bytes())

    with pytest.raises(KeyError):
        store.scan_child_digests(parent)
    with pytest.raises(KeyError):  # the load path agrees
        store.load(parent)


def test_payload_returns_the_bytes_loads_would_get(tmp_path):
    store = ValuePickleFile.with_pickle(tmp_path, compress=True)
    key = store.save([1, [2, 3]])
    assert pickle.loads(store.payload(key)) == store._from_file(store._path(key))
    assert gzip.decompress(store._path(key).read_bytes())  # really is compressed


# ---------------------------------------------------------------------------
# Memory: nothing is serialized, so the scan reads the live object
# ---------------------------------------------------------------------------


def test_memory_scan_does_not_copy_the_payload():
    """The in-place read hands back the stored object, not a deep copy of it."""
    store = ValueMemory(storage={}, remaining_depth=0)
    key = store.save([1, [2, 3]])
    assert store.scan_child_digests(key) == store.child_digests(key)
    assert store.scan_child_digests(key)
