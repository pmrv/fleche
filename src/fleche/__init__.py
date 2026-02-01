"""lru_cache on 'roids."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import wraps
from types import Callable


class MetaData(ABC):
    def pre(self, *args, **kwargs) -> dict:
        ...

    def post(self, pre, *args, **kwargs) -> dict:
        ...

    @property
    @abstractmethod
    def keys(self):
        ...


@dataclass
class Task:
    func: Callable
    meta: tuple[MetaData]

    @property
    def __doc__(self):
        return self.func.__doc__

    def __call__(self, *args, **kwargs):
        result = self.func(*args, **kwargs)
        return result


def fleche(func):
    return Task(func)
