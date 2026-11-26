from app.services.security import generate_key, hash_key


def test_generate_key_format_and_hash():
    result = generate_key()
    raw_key = result["raw_key"]
    key_hash = result["key_hash"]
    safe_preview = result["safe_preview"]

    assert raw_key.startswith("ps_alive_")
    assert len(raw_key) >= 40
    assert key_hash == hash_key(raw_key)
    assert len(key_hash) == 64
    assert safe_preview == raw_key[:12] + "..."
    assert len(safe_preview) == 15


def test_hash_key_deterministic():
    assert hash_key("ps_alive_abc") == hash_key("ps_alive_abc")
    assert hash_key("ps_alive_abc") != hash_key("ps_alive_xyz")
