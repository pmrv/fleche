import os
import hmac
import hashlib
import logging
from dataclasses import dataclass

logger = logging.getLogger("fleche.security")

def get_secret_key() -> bytes | None:
    """
    Retrieve the secret key for signing cache entries.
    Only supports FLECHE_SECRET_KEY environment variable.
    If no key is found, returns None (security is disabled).
    """
    env_key = os.environ.get("FLECHE_SECRET_KEY")
    if env_key:
        return env_key.encode("utf-8")
    return None

@dataclass(slots=True, frozen=True)
class SignedBytes:
    key: bytes | None

    def _sign(self, data: bytes) -> bytes:
        if self.key is None:
            return b""
        return hmac.new(self.key, data, hashlib.sha256).digest()

    def dumps(self, content: bytes) -> bytes:
        if self.key is None:
            return content
        signature = self._sign(content)
        return content + signature

    def loads(self, content: bytes) -> bytes:
        if self.key is None:
            return content

        if len(content) < 32:
            logger.warning("Cache entry too short to be valid signed data. Data may be old/unsigned.")
            return content

        data = content[:-32]
        signature = content[-32:]

        expected_signature = self._sign(data)
        if not hmac.compare_digest(expected_signature, signature):
            logger.warning("Invalid signature for cache entry. Potential tampering or key mismatch.")
            raise KeyError("Invalid signature")

        return data
