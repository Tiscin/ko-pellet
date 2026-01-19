import os
import secrets
from pydantic_settings import BaseSettings
from typing import Optional, List


def generate_secret_key() -> str:
    """Generate and persist a secret key if not provided."""
    key = os.environ.get("SECRET_KEY")
    if key:
        return key

    # Try to load from data directory
    data_dir = os.environ.get("DATA_DIR", "/data")
    key_file = os.path.join(data_dir, ".secret_key")

    if os.path.exists(key_file):
        with open(key_file, "r") as f:
            return f.read().strip()

    # Generate new key
    key = secrets.token_urlsafe(32)

    # Try to persist it
    try:
        os.makedirs(data_dir, exist_ok=True)
        with open(key_file, "w") as f:
            f.write(key)
        os.chmod(key_file, 0o600)
        print(f"Generated new SECRET_KEY and saved to {key_file}")
    except (OSError, IOError) as e:
        print(f"Warning: Could not persist SECRET_KEY: {e}")

    return key


class Settings(BaseSettings):
    # KitchenOwl settings (URL only - token in encrypted storage)
    kitchenowl_url: str = "http://localhost:8080"

    # OIDC settings (bootstrap secrets - required for login flow)
    oidc_issuer: Optional[str] = None  # e.g., https://keycloak.example.com/realms/myrealm
    oidc_client_id: Optional[str] = None
    oidc_client_secret: Optional[str] = None

    # Forward-auth settings (alternative to OIDC)
    forward_auth_enabled: bool = False
    forward_auth_header_user: Optional[str] = None  # e.g., "Remote-User"

    # App settings
    app_url: str = "http://localhost:8000"  # Public URL of this app (for OIDC redirect)
    secret_key: str = ""  # Will be generated if not provided

    # Data directory for persistent storage
    data_dir: str = "/data"

    # SSRF protection - allowlist for internal hosts/IPs for recipe URL imports
    # Comma-separated list of hostnames or IPs that are allowed for recipe imports
    # Example: "kitchenowl.local,recipes.lan,192.168.1.100"
    allowed_internal_hosts: str = ""

    # Trusted proxy IPs (for forward-auth and rate limiting)
    # Comma-separated list of IPs that are allowed to set X-Forwarded-For headers
    # Example: "172.17.0.1,10.0.0.1"
    trusted_proxy_ips: str = ""

    # App settings
    debug: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Generate secret key if not provided
        if not self.secret_key:
            object.__setattr__(self, "secret_key", generate_secret_key())


settings = Settings()


def is_https_app() -> bool:
    """Check if APP_URL uses HTTPS (for cookie Secure flag)."""
    return settings.app_url.lower().startswith("https://")


def get_trusted_proxy_ips() -> set:
    """
    Get the set of trusted proxy IPs/CIDRs as ip_network objects.

    Supports both single IPs (192.168.1.1) and CIDR notation (172.18.0.0/16).
    Single IPs are converted to /32 (IPv4) or /128 (IPv6) networks.
    """
    import ipaddress

    if not settings.trusted_proxy_ips:
        return set()

    networks = set()
    for entry in settings.trusted_proxy_ips.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            if "/" in entry:
                # CIDR notation
                networks.add(ipaddress.ip_network(entry, strict=False))
            else:
                # Single IP - convert to /32 or /128 network
                addr = ipaddress.ip_address(entry)
                prefix = 32 if addr.version == 4 else 128
                networks.add(ipaddress.ip_network(f"{entry}/{prefix}"))
        except ValueError as e:
            print(f"Warning: Invalid TRUSTED_PROXY_IPS entry '{entry}': {e}")

    return networks
