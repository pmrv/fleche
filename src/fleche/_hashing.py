"""The salted running hash every digest is built from.

Kept apart from :mod:`fleche.digest` so that the arm modules it imports
(:mod:`fleche._numbers`, :mod:`fleche._numpy`, :mod:`fleche._pandas`) hash the
same way without importing it back.  The hash primitive lives only here; the
encoding of a finished digest lives here and in :mod:`fleche.digest`'s
``hexdigest()`` returns, never in an arm module.
"""

import hashlib


def new_hash(salt: bytes):
    """Start a running SHA256 under *salt*.

    Every digest is a salted accumulation: the salt discriminates what kind of
    thing is being hashed (a type name, a section of a function's captured
    state) before any content goes in.
    """
    m = hashlib.sha256()
    m.update(salt)
    return m


class running_hash:
    """Context manager over :func:`new_hash`, holding the digest once it exits.

    ::

        with running_hash(salt) as h:
            h.update(part)
        return h.result

    ``result`` is the hex digest as bytes, the form ``_digest_bytes`` returns
    and parent hashes are fed.  It is only set when the block finishes without
    raising: reading it inside the block, or after the block raised, raises
    :exc:`RuntimeError`.
    """

    __slots__ = ("_m", "_result")

    def __init__(self, salt: bytes):
        self._m = new_hash(salt)
        self._result: bytes | None = None

    def __enter__(self) -> "running_hash":
        return self

    def update(self, data: bytes) -> None:
        self._m.update(data)

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self._result = self._m.hexdigest().encode()

    @property
    def result(self) -> bytes:
        if self._result is None:
            raise RuntimeError("running_hash read before its block exited")
        return self._result
