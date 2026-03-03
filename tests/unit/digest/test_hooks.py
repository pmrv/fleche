import pytest

from fleche.digest import Hook, _HOOKS, _EP_HOOKS, add_hook, get_hooks

@pytest.fixture(autouse=True)
def clean_hooks():
    """Fixture to ensure hooks are cleaned before and after each test."""
    _HOOKS.clear()
    _EP_HOOKS.clear()
    yield
    _HOOKS.clear()
    _EP_HOOKS.clear()

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
    """Test get_hooks combines _HOOKS and _EP_HOOKS."""
    def dummy_digest1(x):
        return "dummy1"

    def dummy_digest2(x):
        return "dummy2"

    hook1 = Hook(int, dummy_digest1)
    hook2 = Hook(str, dummy_digest2)

    _HOOKS.append(hook1)
    _EP_HOOKS.append(hook2)

    hooks = get_hooks()

    assert len(hooks) == 2
    assert hooks[0] is hook1
    assert hooks[1] is hook2
    assert hooks == _HOOKS + _EP_HOOKS
