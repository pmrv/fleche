import pytest
from fleche.storage import (
    Memory,
    PickleFile,
    BagOfHoldingH5File,
    Sql,
    CallStorageAdapter,
)
from fleche.caches import Cache

secret_key = [b"test_secret_key_32_bytes_long!!!!"]

@pytest.fixture(params=["memory", "cloudpickle", "dill", "pickle", "h5", "sql"])
def call_storage(request, tmp_path):
    if request.param == "memory":
        return CallStorageAdapter(Memory({}))
    elif request.param == "cloudpickle":
        return CallStorageAdapter(PickleFile.with_cloudpickle(
            tmp_path / "cloudpickle", secret_key=secret_key
        ))
    elif request.param == "dill":
        return CallStorageAdapter(PickleFile.with_dill(tmp_path / "dill", secret_key=secret_key))
    elif request.param == "pickle":
        return CallStorageAdapter(PickleFile.with_pickle(tmp_path / "pickle", secret_key=secret_key))
    elif request.param == "h5":
        return CallStorageAdapter(BagOfHoldingH5File(tmp_path / "h5"))
    elif request.param == "sql":
        return Sql(tmp_path / "calls.db")


@pytest.fixture(params=["memory", "cloudpickle", "dill", "pickle", "h5"])
def value_storage(request, tmp_path):
    if request.param == "memory":
        return Memory({})
    elif request.param == "cloudpickle":
        return PickleFile.with_cloudpickle(
            tmp_path / "cloudpickle", secret_key=secret_key
        )
    elif request.param == "dill":
        return PickleFile.with_dill(tmp_path / "dill", secret_key=secret_key)
    elif request.param == "pickle":
        return PickleFile.with_pickle(tmp_path / "pickle", secret_key=secret_key)
    elif request.param == "h5":
        return BagOfHoldingH5File(tmp_path / "h5")

@pytest.fixture
def clean_cache():
    yield Cache(Memory({}), Memory({}))
