from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request
from starlette.responses import RedirectResponse
from typing import Optional, Dict, Any
import time

from config import settings
from forward_auth import (
    is_forward_auth_enabled,
    get_forward_auth_user,
    create_forward_auth_session,
)

# Initialize OAuth
oauth = OAuth()

# Will be configured on startup if OIDC settings are provided
_oidc_configured = False


def configure_oidc():
    """Configure OIDC provider if settings are available."""
    global _oidc_configured

    if not all([settings.oidc_issuer, settings.oidc_client_id, settings.oidc_client_secret]):
        return False

    oauth.register(
        name="oidc",
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        server_metadata_url=f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration",
        client_kwargs={
            "scope": "openid profile email",
            "token_endpoint_auth_method": "client_secret_post",
        },
    )
    _oidc_configured = True
    return True


def is_oidc_configured() -> bool:
    """Check if OIDC is configured."""
    return _oidc_configured


def is_kitchenowl_auth_available() -> bool:
    """Check if KitchenOwl native auth should be available.

    KO auth activates automatically when neither OIDC nor forward-auth
    is configured and KITCHENOWL_URL is set (always required).
    """
    return not is_oidc_configured() and not is_forward_auth_enabled()


def is_any_auth_configured() -> bool:
    """Check if any authentication method is configured."""
    return is_oidc_configured() or is_forward_auth_enabled() or is_kitchenowl_auth_available()


def get_auth_method() -> Optional[str]:
    """Get the primary authentication method."""
    if is_forward_auth_enabled():
        return "forward_auth"
    if is_oidc_configured():
        return "oidc"
    if is_kitchenowl_auth_available():
        return "kitchenowl"
    return None


async def get_login_redirect(request: Request) -> RedirectResponse:
    """Generate redirect to OIDC provider for login."""
    if not _oidc_configured:
        raise ValueError("OIDC not configured")

    redirect_uri = f"{settings.app_url.rstrip('/')}/api/auth/callback"
    return await oauth.oidc.authorize_redirect(request, redirect_uri)


async def handle_callback(request: Request) -> Dict[str, Any]:
    """Handle OIDC callback and extract tokens."""
    if not _oidc_configured:
        raise ValueError("OIDC not configured")

    token = await oauth.oidc.authorize_access_token(request)

    # Extract user info
    user_info = token.get("userinfo", {})
    if not user_info and "id_token" in token:
        user_info = await oauth.oidc.parse_id_token(token)

    return {
        "access_token": token.get("access_token"),
        "refresh_token": token.get("refresh_token"),
        "expires_at": token.get("expires_at"),
        "token_type": token.get("token_type", "Bearer"),
        "user": {
            "sub": user_info.get("sub"),
            "name": user_info.get("name") or user_info.get("preferred_username"),
            "email": user_info.get("email"),
        },
        "auth_method": "oidc",
    }


async def refresh_access_token(refresh_token: str) -> Optional[Dict[str, Any]]:
    """Refresh the access token using the refresh token."""
    if not _oidc_configured:
        return None

    try:
        # Get token endpoint from metadata
        metadata = await oauth.oidc.load_server_metadata()
        token_endpoint = metadata.get("token_endpoint")

        if not token_endpoint:
            return None

        # Request new token
        async with oauth.oidc._get_oauth_client() as client:
            token = await client.refresh_token(
                token_endpoint,
                refresh_token=refresh_token,
            )

        return {
            "access_token": token.get("access_token"),
            "refresh_token": token.get("refresh_token", refresh_token),
            "expires_at": token.get("expires_at"),
            "token_type": token.get("token_type", "Bearer"),
        }
    except Exception as e:
        print(f"Token refresh failed: {e}")
        return None


def is_token_expired(expires_at: Optional[float]) -> bool:
    """Check if a token is expired (with 60s buffer)."""
    if not expires_at:
        return True
    return time.time() > (expires_at - 60)


def check_forward_auth(request: Request) -> Optional[Dict[str, Any]]:
    """
    Check for forward-auth headers and return session data if present.
    This should be called before checking OIDC session.
    """
    user = get_forward_auth_user(request)
    if user:
        return create_forward_auth_session(user)
    return None


class AuthSession:
    """Helper class to manage auth state in session."""

    SESSION_KEY = "auth"

    @staticmethod
    def get(request: Request) -> Optional[Dict[str, Any]]:
        """Get auth data from session."""
        return request.session.get(AuthSession.SESSION_KEY)

    @staticmethod
    def set(request: Request, auth_data: Dict[str, Any]):
        """Store auth data in session."""
        request.session[AuthSession.SESSION_KEY] = auth_data

    @staticmethod
    def clear(request: Request):
        """Clear auth data from session."""
        request.session.pop(AuthSession.SESSION_KEY, None)

    @staticmethod
    def get_access_token(request: Request) -> Optional[str]:
        """Get access token from session, refreshing if needed."""
        auth = AuthSession.get(request)
        if not auth:
            return None
        return auth.get("access_token")

    @staticmethod
    def is_authenticated(request: Request) -> bool:
        """Check if user is authenticated."""
        auth = AuthSession.get(request)
        if not auth:
            return False
        # Check if token exists (we'll let KitchenOwl tell us if it's expired)
        return bool(auth.get("access_token"))
