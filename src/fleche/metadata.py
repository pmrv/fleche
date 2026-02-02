from abc import ABC, abstractmethod
import time


class MetaData(ABC):
    def pre(self, *args, **kwargs) -> dict:
        ...

    def post(self, pre, *args, **kwargs) -> dict:
        ...

    @property
    @abstractmethod
    def keys(self) -> dict[str, type]:
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...


class Runtime(MetaData):
    def pre(self, *_, **__):
        return {'timestart': time.time()}

    def post(self, pre, *_, **__):
        pre['timestop'] = time.time()
        pre['walltime'] = pre['timestop'] - pre['timestart']
        return pre

    name: str = 'runtime'
    keys = {
            'timestart': float,
            'timestop': float,
            'walltime': float,
    }
