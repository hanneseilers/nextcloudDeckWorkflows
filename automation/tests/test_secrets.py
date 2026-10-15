from __future__ import annotations

import pytest

from automation.config import secrets

cryptography = pytest.importorskip("cryptography", reason="optional dependency, see automation/config/secrets.py")


def test_encrypt_then_decrypt_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(secrets, "SECRET_KEY_PATH", tmp_path / "secret.key")
    secrets.SECRET_KEY_PATH.write_text(secrets.generate_key().decode("ascii"))

    ciphertext = secrets.encrypt("my app password")

    assert secrets.decrypt(ciphertext) == "my app password"


def test_decrypt_fails_with_the_wrong_key(tmp_path, monkeypatch):
    monkeypatch.setattr(secrets, "SECRET_KEY_PATH", tmp_path / "secret.key")
    secrets.SECRET_KEY_PATH.write_text(secrets.generate_key().decode("ascii"))
    ciphertext = secrets.encrypt("my app password")

    secrets.SECRET_KEY_PATH.write_text(secrets.generate_key().decode("ascii"))  # a different key

    from cryptography.fernet import InvalidToken
    with pytest.raises(InvalidToken):
        secrets.decrypt(ciphertext)


def test_missing_key_file_raises_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(secrets, "SECRET_KEY_PATH", tmp_path / "does-not-exist.key")

    with pytest.raises(FileNotFoundError, match="generate-key"):
        secrets.encrypt("anything")
