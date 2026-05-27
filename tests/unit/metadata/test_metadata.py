import getpass
import os
import socket
import subprocess
import time

import pytest

import fleche as fleche_pkg
from fleche import fleche, cache, tags, project, meta
from fleche.caches import Cache
from fleche.metadata import Environment, Git, MetaData, Call, Version
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


def test_version_metadata(cache_it: Cache):
    @fleche(meta=(Version(),))
    def my_function(a: int, b: int) -> int:
        return a + b

    with cache(cache_it):
        my_function(1, 2)
        key = my_function.fleche.digest(1, 2)
        call = cache().calls.load(key)

    assert call.metadata["version"]["fleche"] == fleche_pkg.__version__


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
