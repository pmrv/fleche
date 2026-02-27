import os
import hmac
import hashlib
import logging
import tomllib
from pathlib import Path

logger = logging.getLogger("fleche.security")

def get_secret_key() -> bytes | None:
    """
    Retrieve the secret key for signing cache entries.
    Prioritizes FLECHE_SECRET_KEY environment variable.
    Falls back to a 'secret_key' in the 'security' section of the fleche config file.
    If no key is found, returns None (security is disabled).
    """
    env_key = os.environ.get("FLECHE_SECRET_KEY")
    if env_key:
        return env_key.encode("utf-8")

    # Determine config file path (similar logic to config.py but focusing on loading security config)
    # Re-implementing simplified config finding logic here to avoid circular imports if security is imported in config
    path = None
    if Path("fleche.toml").exists():
        path = Path("fleche.toml").absolute()
    elif "XDG_CONFIG_HOME" in os.environ:
        path = Path(os.environ["XDG_CONFIG_HOME"]) / "fleche" / "cache.toml"
    elif "HOME" in os.environ:
        path = Path(os.environ["HOME"]) / ".fleche.toml"
    else:
        path = Path("~").expanduser() / ".fleche.toml"

    if path and path.exists():
        try:
            with open(path, "rb") as f:
                config = tomllib.load(f)
                if "security" in config and "secret_key" in config["security"]:
                     return config["security"]["secret_key"].encode("utf-8")
        except Exception as e:
            logger.warning("Failed to load secret key from config %s: %s", path, e)

    return None

def sign(data: bytes, key: bytes | None) -> bytes:
    """Sign data using HMAC-SHA256 if key is present."""
    if key is None:
        return b""
    return hmac.new(key, data, hashlib.sha256).digest()

def verify(data: bytes, signature: bytes, key: bytes | None) -> bool:
    """Verify HMAC-SHA256 signature if key is present."""
    if key is None:
        return True
    if not signature or len(signature) != 32:
        return False
    expected = sign(data, key)
    return hmac.compare_digest(expected, signature)
