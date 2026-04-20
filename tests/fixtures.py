import pytest
from fleche.storage import (
    ValueMemory,
    CallMemory,
    ValuePickleFile,
    CallPickleFile,
    ValueBagOfHoldingH5File,
    CallBagOfHoldingH5File,
    Sql,
)
from fleche.storage.memory import MemoryBackend
from fleche.storage.pickle_file import PickleFileBackend
from fleche.storage.bagofholding_file import BagOfHoldingH5FileBackend
from fleche.caches import Cache

secret_key = [b"test_secret_key_32_bytes_long!!!!"]

@pytest.fixture(params=["memory", "cloudpickle", "dill", "pickle", "h5", "sql"])
def call_storage(request, tmp_path):
    if request.param == "memory":
        return CallMemory({})
    elif request.param == "cloudpickle":
        return CallPickleFile.with_cloudpickle(
            tmp_path / "cloudpickle", secret_key=secret_key
        )
    elif request.param == "dill":
        return CallPickleFile.with_dill(tmp_path / "dill", secret_key=secret_key)
    elif request.param == "pickle":
        return CallPickleFile.with_pickle(tmp_path / "pickle", secret_key=secret_key)
    elif request.param == "h5":
        return CallBagOfHoldingH5File(tmp_path / "h5")
    elif request.param == "sql":
        return Sql(tmp_path / "calls.db")


@pytest.fixture(params=["memory", "cloudpickle", "dill", "pickle", "h5"])
def value_storage(request, tmp_path):
    if request.param == "memory":
        return ValueMemory({})
    elif request.param == "cloudpickle":
        return ValuePickleFile.with_cloudpickle(
            tmp_path / "cloudpickle", secret_key=secret_key
        )
    elif request.param == "dill":
        return ValuePickleFile.with_dill(tmp_path / "dill", secret_key=secret_key)
    elif request.param == "pickle":
        return ValuePickleFile.with_pickle(tmp_path / "pickle", secret_key=secret_key)
    elif request.param == "h5":
        return ValueBagOfHoldingH5File(tmp_path / "h5")

@pytest.fixture(params=["memory", "cloudpickle", "dill", "pickle", "h5"])
def storage_backend(request, tmp_path):
    if request.param == "memory":
        return MemoryBackend({})
    elif request.param == "cloudpickle":
        return PickleFileBackend.with_cloudpickle(tmp_path / "cloudpickle")
    elif request.param == "dill":
        return PickleFileBackend.with_dill(tmp_path / "dill")
    elif request.param == "pickle":
        return PickleFileBackend.with_pickle(tmp_path / "pickle")
    elif request.param == "h5":
        return BagOfHoldingH5FileBackend(tmp_path / "h5")


@pytest.fixture
def clean_cache():
    yield Cache(ValueMemory({}), CallMemory({}))
