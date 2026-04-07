"""lru_cache on 'roids."""

try:
    from ._version import __version__
except ImportError:
    __version__ = "unknown"

from . import digest
from .state import (
        cache,
        meta,
        tags,
        project,
)
from .wrapper import fleche, Ignored, Required


def D(value) -> digest.Digest:
    """
    Convenience wrapper to create a Digest from a value.

    If given a non-empty string that is a valid hexadecimal string of at most
    :data:`~fleche.digest.DIGEST_LENGTH` characters, wraps it in a :class:`~fleche.digest.Digest`
    directly (allowing short hex prefixes for use with :meth:`~fleche.digest.Digest.expand`).
    For any other value — including strings that are not valid hex digests — computes the digest.

    .. warning::

        Passing an arbitrary string to ``D()`` will silently compute its digest rather than
        treating the string as a digest identifier.  Only strings that consist entirely of
        hexadecimal characters (``0-9``, ``a-f``, ``A-F``) and are no longer than
        :data:`~fleche.digest.DIGEST_LENGTH` characters are used verbatim.  If you intend to
        look up a cached value by its digest string, make sure the string you pass satisfies
        those constraints; otherwise you will get the digest *of* the string itself, which is
        almost certainly not what you want.

    Digests passed as arguments to @fleche decorated functions are automatically expanded
    to their cached values.
    """
    if isinstance(value, str) and 0 < len(value) <= digest.DIGEST_LENGTH and all(c in "0123456789abcdefABCDEF" for c in value):
        return digest.Digest(value)
    return digest.digest(value)


__all__ = [
        "__version__",
        "fleche",
        "cache",
        "meta",
        "tags",
        "project",
        "Ignored",
        "Required",
        "D",
]
