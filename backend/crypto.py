"""Device key management and AES-256-GCM encryption for secrets storage."""

import os
import secrets
from pathlib import Path
from typing import Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# Device key configuration
DEVICE_KEY_SIZE = 32  # 256 bits for AES-256
NONCE_SIZE = 12  # 96 bits, recommended for GCM


def get_device_key_path() -> Path:
    """Get the path to the device key file."""
    from config import settings
    return Path(settings.data_dir) / ".device_key"


def ensure_device_key() -> bytes:
    """Ensure device key exists, creating it if necessary. Returns the key."""
    key_path = get_device_key_path()

    if key_path.exists():
        return key_path.read_bytes()

    # Generate new device key
    key = secrets.token_bytes(DEVICE_KEY_SIZE)

    # Ensure parent directory exists
    key_path.parent.mkdir(parents=True, exist_ok=True)

    # Write with restricted permissions (owner read/write only)
    old_umask = os.umask(0o077)
    try:
        key_path.write_bytes(key)
    finally:
        os.umask(old_umask)

    # Verify permissions
    key_path.chmod(0o600)

    print(f"Generated new device key at {key_path}")
    return key


def get_device_key() -> Optional[bytes]:
    """Get the device key if it exists."""
    key_path = get_device_key_path()
    if key_path.exists():
        return key_path.read_bytes()
    return None


def encrypt(plaintext: str, key: Optional[bytes] = None) -> bytes:
    """
    Encrypt plaintext using AES-256-GCM.

    Returns: nonce (12 bytes) + ciphertext + tag (16 bytes)
    """
    if key is None:
        key = ensure_device_key()

    if len(key) != DEVICE_KEY_SIZE:
        raise ValueError(f"Key must be {DEVICE_KEY_SIZE} bytes")

    # Generate random nonce
    nonce = secrets.token_bytes(NONCE_SIZE)

    # Create cipher and encrypt
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)

    # Return nonce + ciphertext (ciphertext includes the 16-byte auth tag)
    return nonce + ciphertext


def decrypt(ciphertext_with_nonce: bytes, key: Optional[bytes] = None) -> str:
    """
    Decrypt ciphertext using AES-256-GCM.

    Expects: nonce (12 bytes) + ciphertext + tag (16 bytes)
    """
    if key is None:
        key = get_device_key()
        if key is None:
            raise ValueError("Device key not found")

    if len(key) != DEVICE_KEY_SIZE:
        raise ValueError(f"Key must be {DEVICE_KEY_SIZE} bytes")

    if len(ciphertext_with_nonce) < NONCE_SIZE + 16:  # nonce + minimum tag
        raise ValueError("Ciphertext too short")

    # Extract nonce and ciphertext
    nonce = ciphertext_with_nonce[:NONCE_SIZE]
    ciphertext = ciphertext_with_nonce[NONCE_SIZE:]

    # Create cipher and decrypt
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)

    return plaintext.decode('utf-8')
