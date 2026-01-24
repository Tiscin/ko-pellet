import os
import sys
import logging

# Add backend to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Filter out health check requests from access logs
class HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "/api/health" in message:
            return False
        return True

# Apply filter to uvicorn access logger
logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())

from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Depends, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from starlette.middleware.sessions import SessionMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from typing import Optional
from pydantic import BaseModel

from models import Recipe, ParseRequest, KitchenOwlStatus, RecipeCreateRequest
from config import settings, is_https_app, get_trusted_proxy_ips
from kitchenowl import get_client_for_request
from parsers.url_parser import parse_url
from parsers.text_parser import parse_text
from parsers.image_parser import parse_image
from auth import (
    configure_oidc,
    is_oidc_configured,
    is_any_auth_configured,
    get_auth_method,
    get_login_redirect,
    handle_callback,
    check_forward_auth,
)
from forward_auth import is_forward_auth_enabled
from session_store import (
    create_session,
    get_session,
    set_session,
    delete_session,
    init_session_store,
)
from secrets_store import (
    init_secrets_store,
    get_secret,
    set_secret,
    delete_secret,
    get_secrets_status,
    get_all_secret_keys,
    VALID_SECRETS,
)
from stats_store import (
    record_parse_started,
    record_ai_call,
    record_recipe_saved,
    get_stats,
)

app = FastAPI(title="ko-pellet", version="1.0.0")


def get_client_ip(request: Request) -> str:
    """
    Get the real client IP, handling reverse proxy setups.

    If TRUSTED_PROXY_IPS is configured, uses X-Forwarded-For from trusted proxies.
    Otherwise falls back to direct connection IP.
    """
    import ipaddress

    trusted_networks = get_trusted_proxy_ips()
    client_ip = request.client.host if request.client else "unknown"

    if trusted_networks and client_ip != "unknown":
        # Check if client IP is in a trusted network
        try:
            client_addr = ipaddress.ip_address(client_ip)
            is_trusted = any(client_addr in network for network in trusted_networks)
            if is_trusted:
                # Request is from a trusted proxy - use X-Forwarded-For
                forwarded_for = request.headers.get("X-Forwarded-For")
                if forwarded_for:
                    # X-Forwarded-For can be comma-separated; first IP is the original client
                    return forwarded_for.split(",")[0].strip()
        except ValueError:
            pass  # Invalid IP format, use direct IP

    return client_ip


# Rate limiting with proxy-aware client IP detection
limiter = Limiter(key_func=get_client_ip)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Cookie name for our file-based auth session
AUTH_COOKIE_NAME = "ko_pellet_auth"

# Add session middleware for OIDC state (small data, cookie is fine)
# https_only derived from APP_URL scheme
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="ko_pellet_session",
    max_age=86400 * 7,  # 7 days
    same_site="lax",
    https_only=is_https_app(),
)


@app.on_event("startup")
async def startup():
    """Configure auth, session store, and secrets store on startup."""
    init_session_store()
    init_secrets_store()

    if is_forward_auth_enabled():
        trusted_networks = get_trusted_proxy_ips()
        if not trusted_networks:
            logging.error("=" * 60)
            logging.error("SECURITY MISCONFIGURATION")
            logging.error("=" * 60)
            logging.error("FORWARD_AUTH_ENABLED=true but TRUSTED_PROXY_IPS is not set!")
            logging.error("Forward-auth will REJECT ALL requests until configured.")
            logging.error("")
            logging.error("Set TRUSTED_PROXY_IPS to your reverse proxy's IP/CIDR:")
            logging.error("  Example: TRUSTED_PROXY_IPS=172.18.0.0/16")
            logging.error("  Example: TRUSTED_PROXY_IPS=192.168.1.1,10.0.0.1")
            logging.error("=" * 60)
        else:
            logging.info(f"Forward-auth mode enabled, trusting: {[str(n) for n in trusted_networks]}")
    elif configure_oidc():
        logging.info("OIDC configured successfully")
    else:
        logging.warning("No authentication method configured")
        logging.warning("  Set OIDC_ISSUER, OIDC_CLIENT_ID, and OIDC_CLIENT_SECRET for OIDC")
        logging.warning("  Or set FORWARD_AUTH_ENABLED=true for forward-auth mode")


def get_auth_from_request(request: Request) -> Optional[dict]:
    """Get auth data from file-based session or forward-auth headers."""
    # Check forward-auth first
    forward_auth = check_forward_auth(request)
    if forward_auth:
        return forward_auth

    # Then check file-based session
    session_id = request.cookies.get(AUTH_COOKIE_NAME)
    if not session_id:
        return None
    return get_session(session_id)


def get_access_token_from_request(request: Request) -> Optional[str]:
    """Get access token from file-based session."""
    auth = get_auth_from_request(request)
    if not auth:
        return None
    return auth.get("access_token")


# Dependency to require authentication
async def require_auth(request: Request) -> dict:
    """Require user to be authenticated."""
    auth = get_auth_from_request(request)
    if not auth or not auth.get("access_token"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return auth


# Health check
@app.get("/api/health")
async def health_check():
    return {"status": "healthy"}


# Auth endpoints
@app.get("/api/auth/status")
async def auth_status(request: Request):
    """Get current authentication status."""
    auth = get_auth_from_request(request)
    auth_method = auth.get("auth_method") if auth else None

    if auth and auth.get("access_token"):
        return {
            "authenticated": True,
            "user": auth.get("user"),
            "auth_method": auth_method,
            "oidc_configured": is_oidc_configured(),
            "forward_auth_enabled": is_forward_auth_enabled(),
        }
    return {
        "authenticated": False,
        "user": None,
        "auth_method": None,
        "oidc_configured": is_oidc_configured(),
        "forward_auth_enabled": is_forward_auth_enabled(),
    }


@app.get("/api/auth/login")
@limiter.limit("10/minute")
async def login(request: Request):
    """Redirect to OIDC provider for login."""
    if is_forward_auth_enabled():
        # Forward-auth handles login externally
        raise HTTPException(
            status_code=400,
            detail="Login is handled by your reverse proxy. Please access this app through your proxy."
        )
    if not is_oidc_configured():
        raise HTTPException(status_code=400, detail="OIDC not configured")
    return await get_login_redirect(request)


@app.get("/api/auth/callback")
async def auth_callback(request: Request):
    """Handle OIDC callback."""
    if not is_oidc_configured():
        raise HTTPException(status_code=400, detail="OIDC not configured")

    try:
        auth_data = await handle_callback(request)

        # Create a file-based session and store the auth data
        session_id = create_session()
        set_session(session_id, auth_data)

        # Set cookie server-side with HttpOnly for security
        # Secure flag derived from APP_URL scheme
        from fastapi.responses import RedirectResponse
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            key=AUTH_COOKIE_NAME,
            value=session_id,
            max_age=86400 * 7,  # 7 days
            httponly=True,
            samesite="lax",
            secure=is_https_app(),
        )
        return response
    except Exception as e:
        logging.error(f"Auth callback error: {e}")
        raise HTTPException(status_code=400, detail="Authentication failed")


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    """Log out and clear session."""
    auth = get_auth_from_request(request)
    if auth and auth.get("auth_method") == "forward_auth":
        # For forward-auth, we can't really log out - the proxy controls that
        return {
            "success": True,
            "message": "Logout is handled by your reverse proxy"
        }

    session_id = request.cookies.get(AUTH_COOKIE_NAME)
    if session_id:
        delete_session(session_id)
    response.delete_cookie(AUTH_COOKIE_NAME)
    return {"success": True}


# Secrets API endpoints
class SecretValue(BaseModel):
    value: str


def verify_origin(request: Request) -> None:
    """
    CSRF protection: verify Origin header matches APP_URL for state-changing requests.
    Raises HTTPException if origin is invalid.
    """
    origin = request.headers.get("Origin")
    if not origin:
        # No Origin header - could be same-origin or non-browser client
        # Check Referer as fallback
        referer = request.headers.get("Referer")
        if referer:
            from urllib.parse import urlparse
            referer_origin = f"{urlparse(referer).scheme}://{urlparse(referer).netloc}"
            origin = referer_origin

    if origin:
        # Normalize APP_URL for comparison
        from urllib.parse import urlparse
        expected = urlparse(settings.app_url)
        expected_origin = f"{expected.scheme}://{expected.netloc}"

        if origin != expected_origin:
            logging.warning(f"CSRF check failed: Origin '{origin}' != expected '{expected_origin}'")
            raise HTTPException(status_code=403, detail="Invalid origin")


@app.get("/api/secrets/status")
async def secrets_status(auth: dict = Depends(require_auth)):
    """Get status of which secrets are configured (without revealing values)."""
    return get_secrets_status()


@app.post("/api/secrets/{key}")
async def set_secret_endpoint(key: str, data: SecretValue, request: Request, auth: dict = Depends(require_auth)):
    """Set an encrypted secret."""
    verify_origin(request)

    if key not in VALID_SECRETS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid secret key. Valid keys: {', '.join(sorted(VALID_SECRETS))}"
        )
    try:
        set_secret(key, data.value)
        return {"success": True, "key": key}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/secrets/{key}")
async def delete_secret_endpoint(key: str, request: Request, auth: dict = Depends(require_auth)):
    """Delete a secret."""
    verify_origin(request)

    if key not in VALID_SECRETS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid secret key. Valid keys: {', '.join(sorted(VALID_SECRETS))}"
        )
    try:
        delete_secret(key)
        return {"success": True, "key": key}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Stats endpoint
@app.get("/api/stats")
async def get_lifetime_stats(auth: dict = Depends(require_auth)):
    """Get lifetime usage statistics."""
    return get_stats()


# Parse endpoints (require auth to prevent abuse of AI API quota)
@app.post("/api/parse/url", response_model=Recipe)
@limiter.limit("20/minute")
async def parse_recipe_url(request: Request, request_data: ParseRequest, auth: dict = Depends(require_auth)):
    """Parse a recipe from a URL."""
    if not request_data.url:
        raise HTTPException(status_code=400, detail="URL is required")
    try:
        record_parse_started("url")
        return await parse_url(request_data.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.error(f"URL parse error: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse URL")


MAX_TEXT_LENGTH = 50000  # 50KB of text


@app.post("/api/parse/text", response_model=Recipe)
@limiter.limit("10/minute")
async def parse_recipe_text(request: Request, request_data: ParseRequest, auth: dict = Depends(require_auth)):
    """Parse a recipe from plain text."""
    if not request_data.text:
        raise HTTPException(status_code=400, detail="Text is required")
    if len(request_data.text) > MAX_TEXT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Text too long. Maximum length: {MAX_TEXT_LENGTH} characters"
        )
    try:
        record_parse_started("text")
        record_ai_call()
        return await parse_text(request_data.text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.error(f"Text parse error: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse text")


MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB


# Image magic bytes for validation
IMAGE_MAGIC_BYTES = {
    b'\xff\xd8\xff': 'image/jpeg',
    b'\x89PNG\r\n\x1a\n': 'image/png',
    b'GIF87a': 'image/gif',
    b'GIF89a': 'image/gif',
    b'RIFF': 'image/webp',  # WebP starts with RIFF
}


def validate_image_magic(data: bytes) -> bool:
    """Validate image file by checking magic bytes."""
    for magic, _ in IMAGE_MAGIC_BYTES.items():
        if data.startswith(magic):
            return True
    # WebP has RIFF at start and WEBP at offset 8
    if data[:4] == b'RIFF' and len(data) > 12 and data[8:12] == b'WEBP':
        return True
    return False


@app.post("/api/parse/image", response_model=Recipe)
@limiter.limit("10/minute")
async def parse_recipe_image(request: Request, file: UploadFile = File(...), auth: dict = Depends(require_auth)):
    """Parse a recipe from an uploaded image."""
    allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(allowed_types)}"
        )

    try:
        image_data = await file.read()

        # Enforce file size limit
        if len(image_data) > MAX_IMAGE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"Image too large. Maximum size: {MAX_IMAGE_SIZE // (1024*1024)} MB"
            )

        # Validate actual file content (magic bytes)
        if not validate_image_magic(image_data):
            raise HTTPException(
                status_code=400,
                detail="Invalid image file. File content does not match an allowed image type."
            )

        record_parse_started("image")
        record_ai_call()
        return await parse_image(image_data, file.content_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Image parse error: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse image")


# KitchenOwl endpoints (require auth)
@app.get("/api/kitchenowl/status")
async def kitchenowl_status(request: Request):
    """Check KitchenOwl connection status."""
    client = get_client_for_request(request)
    return await client.check_connection()


@app.get("/api/kitchenowl/households")
async def kitchenowl_households(request: Request, auth: dict = Depends(require_auth)):
    """Get available households."""
    client = get_client_for_request(request)
    try:
        return await client.get_households()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/kitchenowl/check-duplicate/{household_id}")
async def check_duplicate_recipe(
    household_id: int,
    title: str,
    request: Request,
    auth: dict = Depends(require_auth)
):
    """Check if a recipe with similar title already exists."""
    client = get_client_for_request(request)
    try:
        matches = await client.check_duplicate(household_id, title)
        return {
            "has_duplicate": len(matches) > 0,
            "matches": matches
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/kitchenowl/recipe/{household_id}")
async def create_kitchenowl_recipe(
    household_id: int,
    request_data: RecipeCreateRequest,
    request: Request,
    auth: dict = Depends(require_auth)
):
    """Create a recipe in KitchenOwl."""
    client = get_client_for_request(request)
    recipe = request_data.recipe

    try:
        result = await client.create_recipe(household_id, recipe)

        # Record stats for successful save
        record_recipe_saved(
            source_type=recipe.source_type or "url",
            title=recipe.title,
            ingredients_count=len(recipe.ingredients),
            instructions_count=len(recipe.instructions),
            confidence=recipe.confidence.value if hasattr(recipe.confidence, 'value') else str(recipe.confidence),
            tags=recipe.tags or []
        )

        return {"success": True, "recipe": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/kitchenowl/recipes/{household_id}")
async def get_kitchenowl_recipes(
    household_id: int,
    request: Request,
    auth: dict = Depends(require_auth)
):
    """Get recipes from a household."""
    client = get_client_for_request(request)
    try:
        return await client.get_recipes(household_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Settings endpoint (read-only, API keys configured via web UI after login)
@app.get("/api/settings")
async def get_settings():
    """Get current settings (non-sensitive only)."""
    return {
        "kitchenowl_url": settings.kitchenowl_url,
        "oidc_configured": is_oidc_configured(),
        "forward_auth_enabled": is_forward_auth_enabled(),
        "auth_method": get_auth_method(),
    }


# Serve frontend
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")


@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(frontend_path, "index.html"))


# Mount static files for frontend assets
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
