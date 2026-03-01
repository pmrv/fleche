import os
import hmac
import hashlib
import logging
import pickle
from dataclasses import dataclass

logger = logging.getLogger("fleche.security")

class SignatureError(Exception):
    """Exception raised when signature verification fails."""
    pass

def get_secret_key() -> list[bytes]:
    """
    Retrieve the secret key(s) for signing cache entries.

    Only supports FLECHE_SECRET_KEY environment variable.
    If multiple keys are present, they should be comma-separated.
    If no key is found, returns an empty list (security is disabled).

    Returns:
        list[bytes]: A list of secret keys as bytes.
    """
    env_key = os.environ.get("FLECHE_SECRET_KEY")
    if env_key:
        return [k.encode("utf-8") for k in env_key.split(",")]
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
    keys: list[bytes]

    def _sign(self, data: bytes, key: bytes) -> bytes:
        """
        Generate HMAC-SHA256 signature for data using the specified key.

        Args:
            data (bytes): The data to sign.
            key (bytes): The secret key to use for signing.

        Returns:
            bytes: The resulting 32-byte HMAC signature.
        """
        return hmac.new(key, data, hashlib.sha256).digest()

    def dumps(self, content: bytes) -> bytes:
        """
        Signs the content using the first key in the list and appends the signature.
        If no keys are provided, returns the content unmodified.

        Args:
            content (bytes): The serialized data to sign.

        Returns:
            bytes: The original data with the 32-byte signature appended (if keys exist).
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
            logger.warning("Cache entry has no signature. Loading unsigned values. Data may be old/unsigned.")
            return data

        for key in self.keys:
            expected_signature = self._sign(data, key)
            if hmac.compare_digest(expected_signature, signature):
                return data

        logger.warning("Invalid signature for cache entry. Potential tampering or key mismatch.")
        raise SignatureError("Invalid signature")
