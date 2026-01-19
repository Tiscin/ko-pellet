"""Forward-auth support for reverse proxies like Authelia and Authentik."""

import logging
from typing import Optional, Dict, Any
from starlette.requests import Request

from config import settings, get_trusted_proxy_ips


# Common forward-auth headers (in order of preference)
FORWARD_AUTH_HEADERS = [
    "Remote-User",
    "X-Forwarded-User",
    "X-Forwarded-Preferred-Username",
    "X-Auth-Request-User",
]

FORWARD_AUTH_EMAIL_HEADERS = [
    "Remote-Email",
    "X-Forwarded-Email",
    "X-Auth-Request-Email",
]

FORWARD_AUTH_NAME_HEADERS = [
    "Remote-Name",
    "X-Forwarded-Name",
    "X-Auth-Request-Name",
]

FORWARD_AUTH_GROUPS_HEADERS = [
    "Remote-Groups",
    "X-Forwarded-Groups",
    "X-Auth-Request-Groups",
]


def is_forward_auth_enabled() -> bool:
    """Check if forward-auth is enabled."""
    return settings.forward_auth_enabled


def is_request_from_trusted_proxy(request: Request) -> bool:
    """
    Check if the request is coming from a trusted proxy IP/CIDR.

    SECURITY: When forward-auth is enabled, TRUSTED_PROXY_IPS is REQUIRED.
    Returns False if not configured (fail-closed).
    """
    trusted_networks = get_trusted_proxy_ips()
    if not trusted_networks:
        # Fail-closed: no trusted proxies configured
        return False

    # Get the direct client IP
    client_ip = request.client.host if request.client else None
    if not client_ip:
        logging.warning("Could not determine client IP for trusted proxy check")
        return False

    # Check if client IP is in any trusted network/IP
    import ipaddress
    try:
        client_addr = ipaddress.ip_address(client_ip)
        for network in trusted_networks:
            if client_addr in network:
                return True
    except ValueError:
        logging.warning(f"Invalid client IP format: {client_ip}")
        return False

    return False


def get_forward_auth_user(request: Request) -> Optional[Dict[str, Any]]:
    """
    Extract user information from forward-auth headers.

    Returns None if forward-auth is disabled or no user header is present.
    Returns a dict with user info if a valid forward-auth user is found.
    """
    if not is_forward_auth_enabled():
        return None

    # Check if request is from a trusted proxy (if configured)
    if not is_request_from_trusted_proxy(request):
        logging.warning(
            f"Forward-auth request rejected: client IP {request.client.host if request.client else 'unknown'} "
            f"not in TRUSTED_PROXY_IPS"
        )
        return None

    # Get username from configured header or try common headers
    username = None

    if settings.forward_auth_header_user:
        # Use configured header
        username = request.headers.get(settings.forward_auth_header_user)
    else:
        # Try common headers
        for header in FORWARD_AUTH_HEADERS:
            username = request.headers.get(header)
            if username:
                break

    if not username:
        return None

    # Build user info from additional headers
    email = None
    for header in FORWARD_AUTH_EMAIL_HEADERS:
        email = request.headers.get(header)
        if email:
            break

    name = None
    for header in FORWARD_AUTH_NAME_HEADERS:
        name = request.headers.get(header)
        if name:
            break

    groups = None
    for header in FORWARD_AUTH_GROUPS_HEADERS:
        groups_str = request.headers.get(header)
        if groups_str:
            # Groups are typically comma-separated
            groups = [g.strip() for g in groups_str.split(",") if g.strip()]
            break

    return {
        "sub": username,
        "name": name or username,
        "email": email,
        "preferred_username": username,
        "groups": groups,
        "auth_method": "forward_auth",
    }


def create_forward_auth_session(user: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a session-compatible auth data structure from forward-auth user info.
    """
    return {
        "access_token": f"forward_auth:{user['sub']}",  # Synthetic token for internal use
        "refresh_token": None,
        "expires_at": None,  # Forward-auth sessions don't expire internally
        "token_type": "ForwardAuth",
        "user": {
            "sub": user.get("sub"),
            "name": user.get("name"),
            "email": user.get("email"),
        },
        "auth_method": "forward_auth",
    }
