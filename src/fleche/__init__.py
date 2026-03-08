"""lru_cache on 'roids."""

from . import digest
from .state import (
        cache,
        meta,
        tags,
        project,
)
from .wrapper import fleche


def D(d: str) -> digest.Digest:
    """
    Convenience wrapper to create a Digest from a string.

    Digests passed as arguments to @fleche decorated functions are automatically expanded
    to their cached values.
    """
    return digest.Digest(d)


__all__ = [
        fleche,
        cache,
        meta,
        tags,
        project,
]
