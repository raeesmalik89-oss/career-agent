"""Envelope encryption for stored secrets (AES-256-GCM).

Each value gets a fresh random data key; the data key is wrapped with the master key.
Blob layout: version(1) | wrap_nonce(12) | wrapped_dek(48) | data_nonce(12) | ciphertext.
"""

import base64
import os
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

_HEADER = struct.Struct(">B")
_NONCE = 12
_WRAPPED_DEK = 32 + 16


def _master_key() -> bytes:
    key = base64.urlsafe_b64decode(get_settings().master_key)
    if len(key) != 32:
        raise ValueError("MASTER_KEY must be urlsafe-base64 of exactly 32 bytes")
    return key


def encrypt(plaintext: str, associated_data: bytes = b"") -> bytes:
    dek = AESGCM.generate_key(bit_length=256)
    wrap_nonce, data_nonce = os.urandom(_NONCE), os.urandom(_NONCE)
    wrapped = AESGCM(_master_key()).encrypt(wrap_nonce, dek, associated_data)
    ct = AESGCM(dek).encrypt(data_nonce, plaintext.encode(), associated_data)
    return _HEADER.pack(get_settings().master_key_version) + wrap_nonce + wrapped + data_nonce + ct


def decrypt(blob: bytes, associated_data: bytes = b"") -> str:
    offset = _HEADER.size
    wrap_nonce = blob[offset : offset + _NONCE]
    offset += _NONCE
    wrapped = blob[offset : offset + _WRAPPED_DEK]
    offset += _WRAPPED_DEK
    data_nonce = blob[offset : offset + _NONCE]
    offset += _NONCE
    dek = AESGCM(_master_key()).decrypt(wrap_nonce, wrapped, associated_data)
    return AESGCM(dek).decrypt(data_nonce, blob[offset:], associated_data).decode()


def generate_master_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()
