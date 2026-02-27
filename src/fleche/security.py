import os
import hmac
import hashlib
import secrets
import logging
from pathlib import Path

logger = logging.getLogger("fleche.security")

def get_secret_key() -> bytes:
    """
    Retrieve the secret key for signing cache entries.
    Prioritizes FLECHE_SECRET_KEY environment variable.
    Falls back to a file in ~/.fleche/secret.key or XDG_CONFIG_HOME.
    Generates a new key if none exists.
    """
    env_key = os.environ.get("FLECHE_SECRET_KEY")
    if env_key:
        # If the key is hex, decode it? No, let's treat it as raw bytes or string.
        # Ideally user provides a strong random string or hex.
        # For simplicity, if it's a string, we encode it.
        return env_key.encode("utf-8")

    # Determine key file path
    if "XDG_CONFIG_HOME" in os.environ:
        key_path = Path(os.environ["XDG_CONFIG_HOME"]) / "fleche" / "secret.key"
    else:
        key_path = Path.home() / ".fleche" / "secret.key"

    if key_path.exists():
        # Check permissions if possible (posix)
        if os.name == "posix":
            mode = key_path.stat().st_mode
            if mode & 0o077:
                logger.warning(
                    "Secret key file %s has insecure permissions (%s). "
                    "It should be readable only by the owner (0600).",
                    key_path,
                    oct(mode)[-3:],
                )
        return key_path.read_bytes()

    # Generate new key
    key = secrets.token_bytes(32)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    # Write with restrictive permissions
    if os.name == "posix":
        # Create file with 0600 permissions
        # We open the file descriptor with specific flags and mode
        fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
    else:
        # Windows or other OS where we might not easily set 0600 atomically
        key_path.write_bytes(key)

    logger.info("Generated new secret key at %s", key_path)
    return key

def sign(data: bytes, key: bytes) -> bytes:
    """Sign data using HMAC-SHA256."""
    return hmac.new(key, data, hashlib.sha256).digest()

def verify(data: bytes, signature: bytes, key: bytes) -> bool:
    """Verify HMAC-SHA256 signature."""
    if not signature or len(signature) != 32:
        return False
    expected = sign(data, key)
    return hmac.compare_digest(expected, signature)
