import getpass
import os
import platform
import socket
import subprocess
import sys
import time

import pytest

import fleche as fleche_pkg
from fleche import fleche, cache, tags, project, meta
from fleche.caches import Cache
from fleche.metadata import CONFIGURABLE, Environment, Git, MetaData, Runtime, Tags, Call, configurable
from fleche.storage import ValueMemory, CallMemory


@pytest.fixture
def cache_it() -> Cache:
    values_storage = ValueMemory({})
    calls_storage = CallMemory({})
    return Cache(values_storage, calls_storage)


def test_fleche_decorator_default_metadata(cache_it: Cache):
    @fleche
    def my_function(a: int, b: int) -> int:
        return a + b

    with cache(cache_it):
        my_function(1, 2)
        time.sleep(0.1)
        my_function(1, 2)  # cache hit, no new entry

        key = my_function.fleche.digest(1, 2)
        call = cache().calls.load(key)

    assert "runtime" in call.metadata
    assert call.metadata["runtime"]["walltime"] < 0.1


def test_fleche_decorator_custom_metadata(cache_it: Cache):
    class MyMetadata(MetaData):
        name = "my_meta"
        keys = {"my_key": str}

        def pre(self, call: Call):
            return {"my_key": "my_value"}

    @fleche(meta=(MyMetadata(),))
    def my_function(a: int, b: int) -> int:
        return a + b

    with cache(cache_it):
        my_function(1, 2)
        key = my_function.fleche.digest(1, 2)
        call = cache().calls.load(key)

    assert call.metadata.get("my_meta", {}).get("my_key") == "my_value"


def test_metadata_context_manager(cache_it: Cache):
    class MyMetadata(MetaData):
        name = "my_meta"
        keys = {"my_key": str}

        def pre(self, call: Call):
            return {"my_key": "my_value"}

    @fleche
    def my_function(a: int, b: int) -> int:
        return a + b

    with cache(cache_it):
        with meta(MyMetadata()):
            my_function(1, 2)
        key = my_function.fleche.digest(1, 2)
        call = cache().calls.load(key)

    assert call.metadata.get("my_meta", {}).get("my_key") == "my_value"


def test_metadata_context_manager_stacking(cache_it: Cache):
    class MyMetadata1(MetaData):
        name = "my_meta1"
        keys = {"my_key1": str}

        def pre(self, call: Call):
            return {"my_key1": "my_value1"}

    class MyMetadata2(MetaData):
        name = "my_meta2"
        keys = {"my_key2": str}

        def pre(self, call: Call):
            return {"my_key2": "my_value2"}

    @fleche
    def my_function(a: int, b: int) -> int:
        return a + b

    with cache(cache_it):
        with meta(MyMetadata1()):
            with meta(MyMetadata2(), stack=True):
                my_function(1, 2)
        key = my_function.fleche.digest(1, 2)
        call = cache().calls.load(key)

    assert call.metadata.get("my_meta1", {}).get("my_key1") == "my_value1"
    assert call.metadata.get("my_meta2", {}).get("my_key2") == "my_value2"


def test_metadb_table_filtering(cache_it: Cache):
    class MyMetadata(MetaData):
        name = "my_meta"
        keys = {"my_key": str, "my_other_key": int}

        def pre(self, call: Call):
            if call.arguments.get("b") == 2:
                return {"my_key": "my_value", "my_other_key": 1}
            return {"my_key": "another_value", "my_other_key": 2}

    @fleche(meta=(MyMetadata(),))
    def my_function(a: int, b: int) -> int:
        return a + b

    with cache(cache_it):
        my_function(a=1, b=2)
        my_function(a=2, b=3)

        key1 = my_function.fleche.digest(a=1, b=2)
        key2 = my_function.fleche.digest(a=2, b=3)
        call1 = cache().calls.load(key1)
        call2 = cache().calls.load(key2)

    assert call1.metadata["my_meta"]["my_key"] in {"my_value", "another_value"}
    assert call2.metadata["my_meta"]["my_key"] in {"my_value", "another_value"}
    # Verify the conditional split
    assert call1.metadata["my_meta"]["my_key"] == "my_value"
    assert call2.metadata["my_meta"]["my_other_key"] == 2


def test_fleche_decorator_and_context_manager(cache_it: Cache):
    class MyMetadata1(MetaData):
        name = "my_meta1"
        keys = {"my_key1": str}

        def pre(self, call: Call):
            return {"my_key1": "my_value1"}

    class MyMetadata2(MetaData):
        name = "my_meta2"
        keys = {"my_key2": str}

        def pre(self, call: Call):
            return {"my_key2": "my_value2"}

    @fleche(meta=(MyMetadata1(),))
    def my_function(a: int, b: int) -> int:
        return a + b

    with cache(cache_it):
        with meta(MyMetadata2()):
            my_function(1, 2)
        key = my_function.fleche.digest(1, 2)
        call = cache().calls.load(key)

    assert call.metadata.get("my_meta1", {}).get("my_key1") == "my_value1"
    assert call.metadata.get("my_meta2", {}).get("my_key2") == "my_value2"


def test_tags():
    values_storage = ValueMemory({})
    calls_storage = CallMemory({})

    with cache(Cache(values_storage, calls_storage)):

        @fleche
        def my_func(a, b):
            return a + b

        with tags(user="test", project="fleche"):
            my_func(1, 2)
            key1 = my_func.fleche.digest(1, 2)
            call1 = cache().calls.load(key1)
            assert call1.metadata.get("tags", {}).get("user") == "test"
            assert call1.metadata.get("tags", {}).get("project") == "fleche"

        with project("example"):
            my_func(2, 1)
            key2 = my_func.fleche.digest(2, 1)
            call2 = cache().calls.load(key2)
            assert call2.metadata.get("tags", {}).get("project") == "example"


def test_environment_metadata(cache_it: Cache):
    @fleche(meta=(Environment(),))
    def my_function(a: int, b: int) -> int:
        return a + b

    with cache(cache_it):
        my_function(1, 2)
        key = my_function.fleche.digest(1, 2)
        call = cache().calls.load(key)

    env = call.metadata["environment"]
    assert env["hostname"] == socket.gethostname()
    assert env["username"] == getpass.getuser()
    assert env["cwd"] == os.getcwd()
    assert env["fleche_version"] == fleche_pkg.__version__
    assert env["python_version"] == platform.python_version()


def test_git_metadata_inside_repo(cache_it: Cache):
    @fleche(meta=(Git(),))
    def my_function(a: int, b: int) -> int:
        return a + b

    with cache(cache_it):
        my_function(1, 2)
        key = my_function.fleche.digest(1, 2)
        call = cache().calls.load(key)

    git_meta = call.metadata["git"]
    # Test runs from within this repo, so root/commit/branch must resolve.
    assert isinstance(git_meta["root"], str) and git_meta["root"]
    assert isinstance(git_meta["commit"], str) and len(git_meta["commit"]) == 40
    assert isinstance(git_meta["branch"], str) and git_meta["branch"]
    assert isinstance(git_meta["dirty"], bool)


def test_git_metadata_outside_repo(tmp_path, monkeypatch, cache_it: Cache):
    monkeypatch.chdir(tmp_path)

    @fleche(meta=(Git(),))
    def my_function(a: int, b: int) -> int:
        return a + b

    with cache(cache_it):
        my_function(1, 2)
        key = my_function.fleche.digest(1, 2)
        call = cache().calls.load(key)

    assert call.metadata["git"] == {
            "root": None, "commit": None, "branch": None, "dirty": None,
    }


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError("git not installed"),
        subprocess.TimeoutExpired(cmd="git", timeout=2),
    ],
    ids=["missing-binary", "timeout"],
)
def test_git_metadata_when_subprocess_fails(failure, monkeypatch, cache_it: Cache):
    """Git metadata must degrade to all-``None`` when ``git`` cannot run.

    Contract (Git docstring): "All keys are ``None`` when not inside a git
    repository or when the ``git`` executable is missing." A hung or missing
    ``git`` binary must not be allowed to propagate out of metadata collection
    and break the cached call — fleche calls have to remain usable on
    machines without git or when ``git`` itself is unresponsive.
    """
    def raise_failure(*args, **kwargs):
        raise failure

    monkeypatch.setattr("fleche.metadata.subprocess.run", raise_failure)

    @fleche(meta=(Git(),))
    def my_function(a: int, b: int) -> int:
        return a + b

    with cache(cache_it):
        my_function(1, 2)
        key = my_function.fleche.digest(1, 2)
        call = cache().calls.load(key)

    assert call.metadata["git"] == {
        "root": None, "commit": None, "branch": None, "dirty": None,
    }


def test_runtime_metadata_includes_cpu_time(cache_it: Cache):
    @fleche
    def busy_wait():
        x = 0
        for _ in range(2_000_000):
            x += 1
        return x

    with cache(cache_it):
        busy_wait()
        key = busy_wait.fleche.digest()
        call = cache().calls.load(key)

    runtime = call.metadata["runtime"]
    assert runtime["cputime"] >= 0.0
    assert runtime["systime"] >= 0.0


def test_runtime_metadata_counts_subprocess_cpu_time(cache_it: Cache):
    """CPU spent in a spawned subprocess is counted via RUSAGE_CHILDREN."""
    @fleche
    def spin_in_subprocess():
        result = subprocess.run(
            [sys.executable, "-c", "x = 0\nfor _ in range(3_000_000): x += 1"],
            check=True,
        )
        return result.returncode

    with cache(cache_it):
        spin_in_subprocess()
        key = spin_in_subprocess.fleche.digest()
        call = cache().calls.load(key)

    assert call.metadata["runtime"]["cputime"] > 0.0


def test_runtime_metadata_cpu_time_without_resource_module(monkeypatch, cache_it: Cache):
    """``cputime``/``systime`` degrade to ``None`` (rather than raising) where the
    ``resource`` module is unavailable; ``timestart``/``timestop``/``walltime`` are
    unaffected since they don't depend on it."""
    monkeypatch.setattr("fleche.metadata.resource", None)

    @fleche
    def my_function(a: int, b: int) -> int:
        return a + b

    with cache(cache_it):
        my_function(1, 2)
        key = my_function.fleche.digest(1, 2)
        call = cache().calls.load(key)

    runtime = call.metadata["runtime"]
    assert runtime["cputime"] is None
    assert runtime["systime"] is None
    assert isinstance(runtime["walltime"], float)


def test_metadata_default_methods():
    """MetaData should define pre/post method defaults that return empty dictionaries."""
    class MyMetaData(MetaData):
        @property
        def keys(self):
            return {}

        @property
        def name(self):
            return "minimal"

    meta = MyMetaData()
    call = Call(name="test", arguments={})

    assert meta.pre(call) == {}
    assert meta.post({}, call) == {}


def test_configurable_registry_contains_builtins():
    assert CONFIGURABLE == {"Runtime": Runtime, "Environment": Environment, "Git": Git}


def test_configurable_sets_name():
    assert Runtime().name == "runtime"
    assert Environment().name == "environment"
    assert Git().name == "git"


def test_configurable_decorator_registers_and_names():
    @configurable
    class MyMeta(MetaData):
        keys: dict = {}

    try:
        assert MyMeta.name == "mymeta"
        assert CONFIGURABLE.get("MyMeta") is MyMeta
    finally:
        CONFIGURABLE.pop("MyMeta", None)


def test_tags_not_in_configurable():
    assert Tags not in CONFIGURABLE.values()


@pytest.mark.parametrize(
    "cls, expected_keys",
    [
        (
            Runtime,
            {
                "timestart": float,
                "timestop": float,
                "walltime": float,
                "cputime": float,
                "systime": float,
            },
        ),
        (
            Environment,
            {
                "hostname": str,
                "username": str,
                "cwd": str,
                "fleche_version": str,
                "python_version": str,
            },
        ),
        (Git, {"root": str, "commit": str, "branch": str, "dirty": bool}),
    ],
    ids=["runtime", "environment", "git"],
)
def test_builtin_metadata_keys_schema(cls, expected_keys):
    """Zero-arg built-ins publish a fixed schema via the ``keys`` property.

    Contract (``MetaData.keys`` docstring): "Defines the schema of the
    metadata, mapping metadata keys to their expected types."  Downstream
    consumers (e.g. Sql metadata pushdown, future column projection) rely on
    this schema; PR #690 unified ``keys`` as a ``@property`` across every
    built-in so subclass authors implement it exactly one way.  This pins
    each built-in's published schema against its own docstring.
    """
    assert cls().keys == expected_keys


@pytest.mark.parametrize("cls", [Runtime, Environment, Git], ids=["runtime", "environment", "git"])
def test_builtin_metadata_pre_post_keys_match_schema(cls):
    """The keys ``pre``/``post`` actually emit must match the declared ``_keys`` schema.

    Refs #738: before this, each built-in declared its schema twice — once as
    the literal dict keys returned by ``pre``/``post``, once in the ``keys``
    property — with nothing checking the two stayed in sync. Now ``keys``
    reads the single ``_keys`` class attribute, but that only helps if a test
    pins ``_keys`` against what ``pre``/``post`` emit at runtime.
    """
    instance = cls()
    call = Call(name="test", arguments={})
    pre = instance.pre(call)
    post = instance.post(pre, call)
    assert set(pre) | set(post) == set(cls._keys)


def test_tags_keys_derives_from_tag_dict():
    """``Tags.keys`` reflects the tag dict passed at construction time.

    Unlike the ``@configurable`` built-ins (which return a fixed schema),
    ``Tags`` takes a user-supplied ``tags`` dict and infers per-value types
    via ``type(v)`` — an empty dict yields an empty schema, and mixed-type
    values yield a mixed schema.  This is the only ``keys`` property in the
    module that varies per instance rather than per class.
    """
    assert Tags(tags={}).keys == {}
    assert Tags(tags={"user": "test", "n": 3, "on": True}).keys == {
        "user": str,
        "n": int,
        "on": bool,
    }
