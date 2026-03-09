import pytest
import tempfile
import pathlib
from fleche.storage import (
    Memory,
    PickleFile,
    BagOfHoldingH5File,
    Sql,
    CallStorageAdapter,
)

# A function to generate fresh storages so they don't leak state across tests
# when parametrized.

secret_key = [b"test_secret_key_32_bytes_long!!!!"]

# We use global temporary directories for the parameterized lists, but we need
# to make sure the TemporaryDirectory objects don't get garbage collected.
# Otherwise, the directories are deleted, and sqlite files become read-only.

_temp_dirs = []


def _keep_temp(td):
    _temp_dirs.append(td)
    return td


def fresh_value_storages():
    temp1 = _keep_temp(tempfile.TemporaryDirectory())
    temp2 = _keep_temp(tempfile.TemporaryDirectory())
    temp3 = _keep_temp(tempfile.TemporaryDirectory())
    return [
        Memory({}),
        PickleFile.with_cloudpickle(temp1.name, secret_key=secret_key),
        PickleFile.with_dill(temp1.name, secret_key=secret_key),
        PickleFile.with_pickle(temp2.name, secret_key=secret_key),
        BagOfHoldingH5File(temp3.name),
    ]


def fresh_call_storages():
    temp_calls_root = _keep_temp(tempfile.TemporaryDirectory())
    temp_calls_pickle = _keep_temp(tempfile.TemporaryDirectory())
    temp_calls_h5 = _keep_temp(tempfile.TemporaryDirectory())
    temp_calls_sql = _keep_temp(tempfile.TemporaryDirectory())

    return [
        Memory({}),
        PickleFile.with_cloudpickle(temp_calls_root.name, secret_key=secret_key),
        PickleFile.with_dill(temp_calls_root.name, secret_key=secret_key),
        PickleFile.with_pickle(temp_calls_pickle.name, secret_key=secret_key),
        BagOfHoldingH5File(temp_calls_h5.name),
        Sql(pathlib.Path(temp_calls_sql.name) / "calls.db"),
    ]


@pytest.fixture(params=["memory", "cloudpickle", "dill", "pickle", "h5", "sql"])
def call_storage(request, tmp_path):
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
def call_storage_adapter(call_storage):
    if isinstance(call_storage, Sql):
        return call_storage
    return CallStorageAdapter(call_storage)


# Keep these for parameterization when fixtures can't be used
# (like for some hypothesis tests that don't support function scope fixtures)
# but we will just instantiate them when requested

value_storages = fresh_value_storages()
call_storages = fresh_call_storages()
call_storage_adapters = []
for s in fresh_call_storages():
    if isinstance(s, Sql):
        call_storage_adapters.append(s)
    else:
        call_storage_adapters.append(CallStorageAdapter(s))
