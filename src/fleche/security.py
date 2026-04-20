import os
import hmac
import hashlib
import logging
import pickle
from collections.abc import Sequence
from dataclasses import dataclass

logger = logging.getLogger("fleche.security")

class SignatureError(Exception):
    """Exception raised when signature verification fails."""
    pass


def normalize_secret_key(key: bytes | str | Sequence[bytes | str]) -> list[bytes]:
    """
    Normalize a secret key value to ``list[bytes]``.

    Accepts:
    - ``bytes``: wrapped in a list
    - ``str``: interpreted as a hex-encoded key; colon (``:``) separates multiple keys
    - ``list[bytes]``: each element used as-is
    - ``list[str]``: each element interpreted as hex-encoded; colon-delimited parts
      within an element are treated as separate keys

    This is the single normalization path used by both the ``FLECHE_SECRET_KEY``
    environment variable and programmatic ``secret_key`` arguments — so any key
    that can be expressed in the environment variable can also be passed directly,
    and vice-versa.

    Raises:
        TypeError: if ``key`` or any list element is not ``bytes`` or ``str``
        ValueError: if any string part is not valid hex
    """
    if isinstance(key, (bytes, str)):
        key = [key]

    if not isinstance(key, (list, tuple)):
        raise TypeError(
            f"secret_key must be bytes, str, or sequence, got {type(key).__name__}"
        )

    result = []
    for k in key:
        if isinstance(k, str):
            for part in k.split(":"):
                result.append(bytes.fromhex(part))
        elif isinstance(k, bytes):
            result.append(k)
        else:
            raise TypeError(
                f"Each element of secret_key must be bytes or str, "
                f"got {type(k).__name__}"
            )

    return result


def get_secret_key() -> list[bytes]:
    """
    Retrieve the secret key(s) from the ``FLECHE_SECRET_KEY`` environment variable.

    The value must be a colon-separated list of hex-encoded byte strings.
    Returns an empty list if the environment variable is not set (security disabled).

    Uses the same :func:`normalize_secret_key` logic as the programmatic API,
    so any value valid here is also valid as a ``secret_key`` argument and
    vice-versa.

    Returns:
        list[bytes]: A list of secret keys as bytes.
    """
    env_key = os.environ.get("FLECHE_SECRET_KEY")
    if env_key:
        return normalize_secret_key(env_key)
    return []

@dataclass(slots=True, frozen=True)
class SignedBytes:
    """
    Helper class to sign and verify serialized data using HMAC-SHA256.
    Allows for key rotation by accepting a list of keys.

    Args:
        keys (list[bytes]): A list of secret keys. The first key is used for signing,
                            and all keys are attempted during verification.
    """
    keys: Sequence[bytes]

    def _sign(self, data: bytes, key: bytes) -> bytes:
        """
        Generate HMAC-SHA256 hex signature for data using the specified key.
        Hex encoding ensures the signature string (0-9a-f) never contains
        the pickle STOP opcode byte (ASCII 46, `.`).

        Args:
            data (bytes): The data to sign.
            key (bytes): The secret key to use for signing.

        Returns:
            bytes: The resulting 64-byte hex-encoded HMAC signature.
        """
        return hmac.new(key, data, hashlib.sha256).hexdigest().encode("ascii")

    def dumps(self, content: bytes) -> bytes:
        """
        Signs the content using the first key in the list and appends the hex signature.
        If no keys are provided, returns the content unmodified.

        Args:
            content (bytes): The serialized data to sign.

        Returns:
            bytes: The original data with the 64-byte hex signature appended (if keys exist).
        """
        if not self.keys:
            return content
        signature = self._sign(content, self.keys[0])
        return content + signature

    def loads(self, content: bytes) -> bytes:
        """
        Verifies the signature of the content.
        Extracts the signature by searching for the pickle STOP opcode.
        Iterates through all provided keys for verification.
        Returns the original content if verification passes.

        Args:
            content (bytes): The payload containing the data and the appended signature.

        Returns:
            bytes: The original serialized data, stripped of the signature.

        Raises:
            SignatureError: If verification fails, if the data is corrupted, or if the
                            STOP opcode is missing.
        """
        if not self.keys:
            return content

        stop_index = content.rfind(pickle.STOP)

        if stop_index == -1:
            logger.error("No STOP opcode found in cache entry. Data is corrupted or not a pickle.")
            raise SignatureError("No STOP opcode found")

        # The data includes the STOP opcode itself
        data = content[:stop_index + 1]
        signature = content[stop_index + 1:]

        if not signature:
            logger.error("Cache entry has no signature but security is enabled.")
            raise SignatureError("No signature found")

        for key in self.keys:
            expected_signature = self._sign(data, key)
            if hmac.compare_digest(expected_signature, signature):
                return data

        logger.error("Invalid signature for cache entry. Potential tampering or key mismatch.")
        raise SignatureError("Invalid signature")
