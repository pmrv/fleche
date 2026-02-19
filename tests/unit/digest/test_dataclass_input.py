from dataclasses import dataclass, asdict
from unittest.mock import Mock


from fleche import fleche


@dataclass
class Input:
    a: int
    b: float


def test_dataclass_input():
    mock = Mock()
    mock.return_value = 42
    mock.__name__ = 'func'
    func = fleche(mock)

    func(Input(1, 1.0))
    func(Input(1, 1.0))

    func.__wrapped__.assert_called_once()


def test_dict_input():
    mock = Mock()
    mock.return_value = 42
    mock.__name__ = 'func'
    func = fleche(mock)

    func(asdict(Input(1, 1.0)))
    func(asdict(Input(1, 1.0)))

    func.__wrapped__.assert_called_once()
