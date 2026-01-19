"""Encrypted secrets storage with migration support from environment variables."""

import json
import os
import base64
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from crypto import encrypt, decrypt, ensure_device_key


# Valid secret keys
VALID_SECRETS = {
    "kitchenowl_token",
    "anthropic_api_key",
    "openai_api_key",
}

# Environment variable names for migration (lowercase key -> env var name)
ENV_VAR_NAMES = {
    "kitchenowl_token": "KITCHENOWL_TOKEN",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
}

SECRETS_VERSION = 1


def get_secrets_path() -> Path:
    """Get the path to the secrets file."""
    from config import settings
    return Path(settings.data_dir) / "secrets.json"


def _load_secrets_file() -> Dict[str, Any]:
    """Load the secrets file, returning empty structure if not found."""
    secrets_path = get_secrets_path()
    if not secrets_path.exists():
        return {"version": SECRETS_VERSION, "secrets": {}}

    try:
        data = json.loads(secrets_path.read_text())
        # Ensure structure
        if "version" not in data:
            data["version"] = SECRETS_VERSION
        if "secrets" not in data:
            data["secrets"] = {}
        return data
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not read secrets file: {e}")
        return {"version": SECRETS_VERSION, "secrets": {}}


def _save_secrets_file(data: Dict[str, Any]) -> None:
    """Save the secrets file with restricted permissions."""
    secrets_path = get_secrets_path()

    # Ensure parent directory exists
    secrets_path.parent.mkdir(parents=True, exist_ok=True)

    # Write with restricted permissions
    old_umask = os.umask(0o077)
    try:
        secrets_path.write_text(json.dumps(data, indent=2))
    finally:
        os.umask(old_umask)

    # Verify permissions
    secrets_path.chmod(0o600)


def init_secrets_store() -> None:
    """Initialize secrets store and perform migration from environment variables."""
    # Ensure device key exists
    ensure_device_key()

    # Check if we need to migrate from environment variables
    secrets_path = get_secrets_path()
    if not secrets_path.exists():
        _migrate_from_env()


def _migrate_from_env() -> None:
    """Migrate secrets from environment variables to encrypted storage."""
    migrated = []

    for key, env_var in ENV_VAR_NAMES.items():
        value = os.environ.get(env_var)
        if value:
            set_secret(key, value)
            migrated.append(key)
            print(f"Migrated {env_var} to encrypted storage")

    if migrated:
        print(f"Migration complete: {len(migrated)} secret(s) migrated")
        print("You can now remove these values from your .env file:")
        for key in migrated:
            print(f"  - {ENV_VAR_NAMES[key]}")
    else:
        print("No secrets to migrate from environment variables")


def get_secret(key: str) -> Optional[str]:
    """
    Get a decrypted secret by key.
    Falls back to environment variable if not in encrypted store (for backward compatibility).
    """
    if key not in VALID_SECRETS:
        raise ValueError(f"Invalid secret key: {key}")

    # Try encrypted store first
    data = _load_secrets_file()
    secret_data = data.get("secrets", {}).get(key)

    if secret_data and "encrypted" in secret_data:
        try:
            encrypted_bytes = base64.b64decode(secret_data["encrypted"])
            return decrypt(encrypted_bytes)
        except Exception as e:
            print(f"Warning: Could not decrypt secret {key}: {e}")

    # Fall back to environment variable (deprecated, for transition)
    env_var = ENV_VAR_NAMES.get(key)
    if env_var:
        value = os.environ.get(env_var)
        if value:
            return value

    return None


def set_secret(key: str, value: str) -> None:
    """Encrypt and store a secret."""
    if key not in VALID_SECRETS:
        raise ValueError(f"Invalid secret key: {key}")

    if not value:
        delete_secret(key)
        return

    # Encrypt the value
    encrypted_bytes = encrypt(value)
    encrypted_b64 = base64.b64encode(encrypted_bytes).decode('ascii')

    # Load, update, save
    data = _load_secrets_file()
    data["secrets"][key] = {
        "encrypted": encrypted_b64,
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    _save_secrets_file(data)


def delete_secret(key: str) -> None:
    """Delete a secret from the store."""
    if key not in VALID_SECRETS:
        raise ValueError(f"Invalid secret key: {key}")

    data = _load_secrets_file()
    if key in data.get("secrets", {}):
        del data["secrets"][key]
        _save_secrets_file(data)


def get_secrets_status() -> Dict[str, Any]:
    """
    Get status of which secrets are configured (without revealing values).
    Returns dict with secret names as keys and configuration status.
    """
    result = {}

    for key in VALID_SECRETS:
        secret = get_secret(key)
        result[key] = {
            "configured": bool(secret),
        }

        # Get updated_at from the file if available
        data = _load_secrets_file()
        secret_data = data.get("secrets", {}).get(key, {})
        if "updated_at" in secret_data:
            result[key]["updated_at"] = secret_data["updated_at"]

    return result


def get_all_secret_keys() -> List[str]:
    """Get list of all valid secret keys."""
    return list(VALID_SECRETS)
