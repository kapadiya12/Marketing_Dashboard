"""Encryption for stored integration credentials (Fernet, AES-128-CBC + HMAC)."""
import base64
import hashlib
import json

from django.conf import settings


def _fernet():
    from cryptography.fernet import Fernet

    key = settings.INTEGRATION_ENCRYPTION_KEY
    if not key:
        # Derive a stable key from SECRET_KEY when no dedicated key is configured.
        key = base64.urlsafe_b64encode(hashlib.sha256(("integrations:" + settings.SECRET_KEY).encode()).digest())
    return Fernet(key)


def encrypt_json(data):
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_json(token):
    if not token:
        return {}
    from cryptography.fernet import InvalidToken

    try:
        return json.loads(_fernet().decrypt(token.encode()).decode())
    except (InvalidToken, ValueError):
        return {}
