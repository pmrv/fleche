
from unittest.mock import Mock
from fleche import fleche

def test_fleche_no_args():
    @fleche
    def my_func(x):
        return x * 2

    assert my_func(2) == 4

def test_fleche_with_args():
    @fleche()
    def my_func(x):
        return x * 2

    assert my_func(2) == 4

def test_fleche_with_meta():
    mock_meta = Mock()
    mock_meta.name = "my_meta"

    @fleche(meta=(mock_meta,))
    def my_func(x):
        return x * 2

    assert my_func(2) == 4
    mock_meta.pre.assert_called_once_with(2)
    mock_meta.post.assert_called_once()
