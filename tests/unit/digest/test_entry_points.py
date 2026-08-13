import logging

import pytest
from unittest.mock import MagicMock, patch
from fleche.digest import (
    digest,
    Indigestible,
    Hook,
    _HOOKS,
    _EP_HOOKS,
    load_entry_points,
    add_hook,
    get_hooks,
)


@pytest.fixture(autouse=True)
def clean_hooks():
    """Fixture to ensure hooks are cleaned before and after each test."""
    _HOOKS.clear()
    _EP_HOOKS.clear()
    yield
    _HOOKS.clear()
    _EP_HOOKS.clear()


class CustomType:
    def __init__(self, value):
        self.value = value


def custom_digest(obj):
    return f"custom:{obj.value}"


def test_entry_point_discovery():
    """
    Test that entry points are automatically discovered and loaded when an
    Indigestible error occurs.
    """
    obj = CustomType("test")

    # Initially it should fail
    with pytest.raises(Indigestible):
        digest(obj)

    # Mock entry point
    mock_ep = MagicMock()
    mock_ep.name = "custom_type"
    mock_ep.value = "some.module:hook"
    mock_ep.load.return_value = Hook(CustomType, custom_digest)

    with patch("importlib.metadata.entry_points") as mock_entry_points:
        mock_entry_points.return_value = [mock_ep]

        # This should now succeed and discovery should have happened
        result = digest(obj)
        assert result == "custom:test"
        mock_entry_points.assert_called_with(group="fleche", name="digest")


def test_entry_point_list_discovery():
    """
    Test that entry points returning a list of Hook objects are correctly handled.
    """
    obj = CustomType("test")

    mock_ep = MagicMock()
    mock_ep.load.return_value = [Hook(CustomType, custom_digest)]

    with patch("importlib.metadata.entry_points") as mock_entry_points:
        mock_entry_points.return_value = [mock_ep]
        result = digest(obj)
        assert result == "custom:test"


def test_add_hook_priority():
    """
    Test that hooks manually added via add_hook take precedence over entry points,
    and that an INFO message is logged when an entry point is overridden.
    """

    def manual_digest(obj):
        return f"manual:{obj.value}"

    add_hook(Hook(CustomType, manual_digest))

    obj = CustomType("test")

    mock_ep = MagicMock()
    mock_ep.name = "ep_name"
    mock_ep.load.return_value = Hook(CustomType, custom_digest)

    with patch("importlib.metadata.entry_points") as mock_entry_points:
        mock_entry_points.return_value = [mock_ep]

        # Manually trigger loading to verify priority and logging
        load_entry_points()

        result = digest(obj)
        assert result == "manual:test"


def test_multiple_entry_points():
    """
    Test that when multiple entry points provide different hooks for the same type,
    the first one is used.
    """
    mock_ep1 = MagicMock()
    mock_ep1.name = "ep1"
    mock_ep1.load.return_value = Hook(CustomType, custom_digest)

    def another_digest(obj):
        return "another"

    mock_ep2 = MagicMock()
    mock_ep2.name = "ep2"
    mock_ep2.load.return_value = Hook(CustomType, another_digest)

    with patch("importlib.metadata.entry_points") as mock_entry_points:
        mock_entry_points.return_value = [mock_ep1, mock_ep2]

        # Manually trigger loading
        load_entry_points()

        assert digest(CustomType(4)) == custom_digest(CustomType(4))


def test_add_hook_with_hook_instance():
    """Test adding a Hook instance appends it to _HOOKS."""

    def dummy_digest(x):
        return "dummy"

    hook = Hook(int, dummy_digest)
    add_hook(hook)

    assert len(_HOOKS) == 1
    assert _HOOKS[0] is hook


def test_add_hook_with_tuple():
    """Test adding a tuple automatically converts it to a Hook instance."""

    def dummy_digest(x):
        return "dummy"

    hook_tuple = (str, dummy_digest)
    add_hook(hook_tuple)

    assert len(_HOOKS) == 1
    assert isinstance(_HOOKS[0], Hook)
    assert _HOOKS[0].type is str
    assert _HOOKS[0].digest is dummy_digest


def test_get_hooks():
    """Test get_hooks combines _HOOKS (reversed) and _EP_HOOKS."""

    def dummy_digest1(x):
        return "dummy1"

    def dummy_digest2(x):
        return "dummy2"

    def dummy_digest3(x):
        return "dummy3"

    hook1 = Hook(int, dummy_digest1)
    hook2 = Hook(float, dummy_digest2)
    hook3 = Hook(str, dummy_digest3)

    _HOOKS.append(hook1)
    _HOOKS.append(hook2)
    _EP_HOOKS.append(hook3)

    hooks = get_hooks()

    assert len(hooks) == 3
    # _HOOKS are reversed so last-added has priority
    assert hooks[0] is hook2
    assert hooks[1] is hook1
    # EP hooks follow after
    assert hooks[2] is hook3


def test_multiple_entry_points_logs_single_correct_override(caplog):
    """The duplicate-hook log should fire exactly once and name the actual
    winning/losing entry points, not scan through unrelated hooks."""
    mock_ep1 = MagicMock()
    mock_ep1.name = "ep1"
    mock_ep1.value = "pkg.ep1:hook"
    mock_ep1.load.return_value = Hook(CustomType, custom_digest)

    def another_digest(obj):
        return "another"

    mock_ep2 = MagicMock()
    mock_ep2.name = "ep2"
    mock_ep2.value = "pkg.ep2:hook"
    mock_ep2.load.return_value = Hook(CustomType, another_digest)

    with patch("importlib.metadata.entry_points") as mock_entry_points:
        mock_entry_points.return_value = [mock_ep1, mock_ep2]

        with caplog.at_level(logging.INFO, logger="fleche.digest"):
            load_entry_points()

    override_records = [
        r for r in caplog.records if "ignoring entry point" in r.getMessage()
    ]
    assert len(override_records) == 1
    assert override_records[0].getMessage() == (
        f"pkg.ep1:hook already provides a digest for {CustomType!r}; "
        "ignoring entry point pkg.ep2:hook"
    )

    # the losing hook must not have been registered
    assert [h.digest for h in _EP_HOOKS] == [custom_digest]


def test_add_hook_lifo_priority():
    """Test that hooks added later via add_hook take precedence over earlier ones."""

    def first_digest(obj):
        return "first"

    def second_digest(obj):
        return "second"

    add_hook(Hook(CustomType, first_digest))
    add_hook(Hook(CustomType, second_digest))

    obj = CustomType("test")
    assert digest(obj) == "second"
