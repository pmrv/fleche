import os
import hmac
import hashlib
import logging
import pickle
from dataclasses import dataclass, field

logger = logging.getLogger("fleche.security")

class SignatureError(Exception):
    """Exception raised when signature verification fails."""
    pass

def get_secret_key() -> list[bytes] | None:
    """
    Retrieve the secret key(s) for signing cache entries.
    Only supports FLECHE_SECRET_KEY environment variable.
    If multiple keys are present, they should be comma-separated.
    If no key is found, returns None (security is disabled).
    """
    env_key = os.environ.get("FLECHE_SECRET_KEY")
    if env_key:
        return [k.encode("utf-8") for k in env_key.split(",")]
    return None

@dataclass(slots=True, frozen=True)
class SignedBytes:
    keys: list[bytes] | bytes | None

    @property
    def _keys_list(self) -> list[bytes]:
        if self.keys is None:
            return []
        if isinstance(self.keys, bytes):
            return [self.keys]
        return self.keys

    def _sign(self, data: bytes, key: bytes) -> bytes:
        return hmac.new(key, data, hashlib.sha256).digest()

    def dumps(self, content: bytes) -> bytes:
        keys = self._keys_list
        if not keys:
            return content
        signature = self._sign(content, keys[0])
        return content + signature

    def loads(self, content: bytes) -> bytes:
        keys = self._keys_list
        if not keys:
            return content

        # Specifically search for the STOP opcode from the back
        # The pickle STOP opcode is b"." (ASCII 46)
        stop_index = content.rfind(pickle.STOP)

        if stop_index == -1:
            # If we can't find the STOP opcode, something is very wrong, but we can try to fall back
            # or raise an error. The reviewer asked to search for STOP to separate data and signature.
            # If it's not a pickle at all, we'll let it fail verification.
            logger.warning("No STOP opcode found in cache entry. Data is corrupted or not a pickle.")
            raise SignatureError("No STOP opcode found")

        # The data includes the STOP opcode itself
        data = content[:stop_index + 1]
        signature = content[stop_index + 1:]

        if not signature:
            logger.warning("Cache entry has no signature. Loading unsigned values. Data may be old/unsigned.")
            return data

        for key in keys:
            expected_signature = self._sign(data, key)
            if hmac.compare_digest(expected_signature, signature):
                return data

        logger.warning("Invalid signature for cache entry. Potential tampering or key mismatch.")
        raise SignatureError("Invalid signature")
