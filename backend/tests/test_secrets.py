from app.core.secrets import decrypt_credentials, encrypt_credentials, mask_secret


def test_roundtrip_and_mask():
    blob = encrypt_credentials({"api_key": "sk-abcdefghijklmnop"})
    assert "sk-" not in blob
    assert decrypt_credentials(blob) == {"api_key": "sk-abcdefghijklmnop"}
    assert decrypt_credentials(None) == {}
    assert mask_secret("sk-abcdefghijklmnop") == "sk-…mnop"
    assert mask_secret("short") == "*****"
