"""AES-256-GCM envelope encryption for connection secrets.

Two keys are involved: a per-record Data Encryption Key (DEK), generated fresh
for every secret, and a Key Encryption Key (KEK) held in Supabase Vault and
fetched only inside :mod:`backend.db.vault`. The DEK encrypts the actual
secret payload; the KEK encrypts (wraps) the DEK. Nothing here ever persists
a DEK or a decrypted payload — callers get back either ciphertext (for
storage) or a short-lived plaintext dict (for immediate use), never both at
once outside this module's own stack frame.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_LEN = 12  # 96-bit nonce, the size AESGCM expects.


@dataclass(frozen=True)
class Envelope:
    """Ciphertext-only bundle — safe to persist, safe to log."""

    secret_ciphertext: bytes
    secret_nonce: bytes
    wrapped_dek: bytes
    dek_nonce: bytes


def encrypt_secret(payload: dict, kek: bytes) -> Envelope:
    """Encrypt ``payload`` under a fresh DEK, then wrap that DEK under ``kek``."""
    dek = os.urandom(32)
    try:
        payload_bytes = json.dumps(payload).encode("utf-8")

        secret_nonce = os.urandom(_NONCE_LEN)
        secret_ciphertext = AESGCM(dek).encrypt(secret_nonce, payload_bytes, None)

        dek_nonce = os.urandom(_NONCE_LEN)
        wrapped_dek = AESGCM(kek).encrypt(dek_nonce, dek, None)
    finally:
        dek = b"\x00" * len(dek)  # best-effort scrub; CPython gives no hard guarantee

    return Envelope(
        secret_ciphertext=secret_ciphertext,
        secret_nonce=secret_nonce,
        wrapped_dek=wrapped_dek,
        dek_nonce=dek_nonce,
    )


def decrypt_secret(envelope: Envelope, kek: bytes) -> dict:
    """Reverse of :func:`encrypt_secret` — unwrap the DEK, then decrypt the payload.

    Returns a plain dict intended for immediate, in-memory use by a connector.
    Callers must not cache, log, or persist the result.
    """
    dek = AESGCM(kek).decrypt(envelope.dek_nonce, envelope.wrapped_dek, None)
    try:
        payload_bytes = AESGCM(dek).decrypt(envelope.secret_nonce, envelope.secret_ciphertext, None)
    finally:
        dek = b"\x00" * len(dek)
    return json.loads(payload_bytes.decode("utf-8"))
