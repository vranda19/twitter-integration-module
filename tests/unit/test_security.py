"""
tests/unit/test_security.py

Unit tests for app/core/security.py — token encryption round-trip and
tamper detection. Critical to get right since a bug here means either
leaking plaintext tokens or corrupting stored ones irrecoverably.
"""

import pytest

from app.core.security import decrypt_token, encrypt_token


def test_encrypt_decrypt_round_trip():
    plaintext = "super-secret-access-token-value"
    ciphertext = encrypt_token(plaintext)

    assert ciphertext != plaintext
    assert decrypt_token(ciphertext) == plaintext


def test_encrypted_value_is_not_deterministic():
    """Fernet includes a random IV — encrypting the same value twice must differ, preventing pattern analysis."""
    plaintext = "same-token-both-times"
    first = encrypt_token(plaintext)
    second = encrypt_token(plaintext)

    assert first != second
    assert decrypt_token(first) == decrypt_token(second) == plaintext


def test_tampered_ciphertext_raises_error():
    ciphertext = encrypt_token("original-token")
    tampered = ciphertext[:-4] + "abcd"

    with pytest.raises(RuntimeError):
        decrypt_token(tampered)
