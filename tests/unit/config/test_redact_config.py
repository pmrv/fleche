"""Redaction of credentials in configs produced by ``cache_to_config``."""

from fleche.config import SENSITIVE_CONFIG_KEYS, redact_config, redact_url_password


def test_redact_config_replaces_secret_key():
    """`secret_key` values are replaced, whatever backend dict carries them."""
    raw = {
        "values": {"type": "cloudpickle", "root": "/x", "secret_key": ["a" * 64]},
        "calls": {"type": "cloudpickle", "root": "/y", "secret_key": ["b" * 64]},
    }
    redacted = redact_config(raw)
    assert redacted["values"]["secret_key"] == "<redacted>"
    assert redacted["calls"]["secret_key"] == "<redacted>"
    # Non-sensitive fields pass through.
    assert redacted["values"]["root"] == "/x"


def test_redact_url_password_masks_only_the_password():
    """URL passwords in non-sqlite SQL configs are masked."""
    assert (
        redact_url_password("postgresql://alice:hunter2@db.example.com:5432/x")
        == "postgresql://alice:***@db.example.com:5432/x"
    )
    # No password component → pass through.
    assert (
        redact_url_password("sqlite:///tmp/foo.db")
        == "sqlite:///tmp/foo.db"
    )
    assert (
        redact_url_password("postgresql://alice@db.example.com/x")
        == "postgresql://alice@db.example.com/x"
    )


def testredact_config_walks_stack_with_nested_sql_url():
    """`redact_config` recurses through list-shaped stack configs and masks nested SQL URLs.

    :func:`cache_to_config` serialises a :class:`~fleche.caches.CacheStack` as a
    top-level list of member dicts.  A member with a :class:`~fleche.storage.sql.Sql`
    call storage carries the DB password inside its nested ``calls.url``.  Both
    the list traversal (recursion into each member) and the nested ``url``
    rewrite must fire for a stack of SQL caches not to leak the password.  The
    primitives are exercised in isolation by
    ``test_redact_config_replaces_secret_key`` /
    ``test_redact_url_password_masks_only_the_password``; this
    test pins their composition on the shape ``cache_to_config`` produces.
    """
    stack_config = [
        {
            "values": {"type": "memory"},
            "calls": {
                "type": "sql",
                "url": "postgresql://alice:hunter2@db.example.com:5432/x",
            },
        },
        {
            "values": {"type": "memory"},
            "calls": {"type": "memory"},
        },
    ]
    redacted = redact_config(stack_config)
    assert isinstance(redacted, list)
    assert len(redacted) == 2
    assert (
        redacted[0]["calls"]["url"]
        == "postgresql://alice:***@db.example.com:5432/x"
    )
    assert redacted[1]["calls"] == {"type": "memory"}


def test_redact_config_leaves_its_input_alone():
    """The result is a copy; the config passed in keeps its credentials."""
    raw = {"values": {"secret_key": ["a" * 64]}, "calls": {"url": "postgresql://u:pw@h/x"}}
    redact_config(raw)
    assert raw == {"values": {"secret_key": ["a" * 64]}, "calls": {"url": "postgresql://u:pw@h/x"}}


def test_every_sensitive_key_is_redacted():
    raw = {key: "credential" for key in SENSITIVE_CONFIG_KEYS}
    assert redact_config(raw) == {key: "<redacted>" for key in SENSITIVE_CONFIG_KEYS}


def test_redact_config_passes_scalars_through():
    for value in ("postgresql://u:pw@h/x", 3, None, True):
        assert redact_config(value) is value
