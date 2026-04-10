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

@pytest.fixture
def clean_cache():
    yield Cache(ValueMemory({}), CallMemory({}))
