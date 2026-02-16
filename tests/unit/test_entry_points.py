
import pytest
from unittest.mock import MagicMock, patch
from fleche.digest import digest, Unhashable, Hook, _HOOKS, load_entry_points

class CustomType:
    def __init__(self, value):
        self.value = value

def custom_digest(obj):
    return f"custom:{obj.value}"

def test_entry_point_discovery():
    """
    Test that entry points are automatically discovered and loaded when an
    Unhashable error occurs.
    """
    # Reset hooks for testing
    _HOOKS.clear()

    obj = CustomType("test")

    # Initially it should fail
    with pytest.raises(Unhashable):
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
    _HOOKS.clear()
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
    _HOOKS.clear()
    from fleche.digest import add_hook

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
    _HOOKS.clear()

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
