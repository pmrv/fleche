from dataclasses import dataclass


@dataclass
class Invocation:
    name: str
    args: tuple
    kwargs: dict
