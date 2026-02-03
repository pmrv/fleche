from dataclasses import dataclass
from typing import Any


@dataclass
class Invocation:
    """
    Represents a function invocation, capturing its name, arguments, and keyword arguments.
    """
    name: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
