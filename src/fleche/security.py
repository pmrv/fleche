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
    """
    keys: list[bytes]

    def _sign(self, data: bytes, key: bytes) -> bytes:
        return hmac.new(key, data, hashlib.sha256).digest()

    def dumps(self, content: bytes) -> bytes:
        """
        Signs the content using the first key in the list and appends the signature.
        If no keys are provided, returns the content unmodified.
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
        Raises SignatureError if verification fails or data is corrupted.
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
