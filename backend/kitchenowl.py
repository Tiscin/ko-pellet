import asyncio
import httpx
import logging
import time
from starlette.requests import Request
from typing import Optional, Dict, Any, List
from models import Recipe, KitchenOwlStatus
from config import settings
from secrets_store import get_secret

# Per-session locks to prevent concurrent refresh token races.
# Key: session_id, Value: asyncio.Lock
# Bounded to prevent memory leak from abandoned sessions.
_refresh_locks: Dict[str, asyncio.Lock] = {}
_MAX_REFRESH_LOCKS = 1000


class KitchenOwlClient:
    """Client for interacting with KitchenOwl API."""

    def __init__(self, base_url: Optional[str] = None, access_token: Optional[str] = None):
        self.base_url = (base_url or settings.kitchenowl_url).rstrip("/")
        self.access_token = access_token

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    async def check_connection(self) -> KitchenOwlStatus:
        """Check if we can connect to KitchenOwl."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # First check if KitchenOwl is reachable
                try:
                    response = await client.get(f"{self.base_url}/api/health")
                    if response.status_code == 200:
                        # Server is up, now check auth
                        if not self.access_token:
                            return KitchenOwlStatus(
                                connected=False,
                                url=self.base_url,
                                error="Not logged in"
                            )
                except Exception:
                    pass  # Health endpoint might not exist

                # Try user endpoint to verify auth
                response = await client.get(
                    f"{self.base_url}/api/user",
                    headers=self._get_headers()
                )
                if response.status_code == 200:
                    return KitchenOwlStatus(connected=True, url=self.base_url)
                elif response.status_code == 401:
                    return KitchenOwlStatus(
                        connected=False,
                        url=self.base_url,
                        error="Not logged in" if not self.access_token else "Session expired"
                    )
                else:
                    return KitchenOwlStatus(
                        connected=False,
                        url=self.base_url,
                        error=f"Unexpected response: {response.status_code}"
                    )
        except httpx.ConnectError:
            return KitchenOwlStatus(
                connected=False,
                url=self.base_url,
                error="Could not connect to KitchenOwl server"
            )
        except Exception as e:
            return KitchenOwlStatus(
                connected=False,
                url=self.base_url,
                error=str(e)
            )

    async def get_households(self) -> List[Dict[str, Any]]:
        """Get list of households the user has access to."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self.base_url}/api/household",
                headers=self._get_headers()
            )
            response.raise_for_status()
            return response.json()

    async def get_recipes(self, household_id: int) -> List[Dict[str, Any]]:
        """Get existing recipes from a household."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self.base_url}/api/household/{household_id}/recipe",
                headers=self._get_headers()
            )
            response.raise_for_status()
            return response.json()

    async def create_recipe(self, household_id: int, recipe: Recipe) -> Dict[str, Any]:
        """Create a new recipe in KitchenOwl."""
        # Format recipe for KitchenOwl API
        # KitchenOwl expects ingredients as a list of item objects
        items = []
        for ing in recipe.ingredients:
            item = {
                "name": ing.name,
            }
            # Build description from quantity and unit
            desc_parts = []
            if ing.quantity:
                desc_parts.append(ing.quantity)
            if ing.unit:
                desc_parts.append(ing.unit)
            if ing.note:
                desc_parts.append(f"({ing.note})")
            if desc_parts:
                item["description"] = " ".join(desc_parts)
            items.append(item)

        # Format time (KitchenOwl expects minutes as integer)
        time_value = recipe.total_time or recipe.cook_time or recipe.prep_time

        # Build description with instructions using markdown
        desc_parts = []
        if recipe.description:
            desc_parts.append(recipe.description)
        if recipe.instructions:
            steps = [f"1. {step}" for step in recipe.instructions]  # Markdown auto-numbers
            desc_parts.append("## Instructions\n\n" + "\n".join(steps))
        if recipe.notes:
            desc_parts.append(f"## Notes\n\n{recipe.notes}")
        full_description = "\n\n".join(desc_parts) if desc_parts else ""

        payload = {
            "name": recipe.title,
            "description": full_description,
        }

        if recipe.source_url:
            payload["source"] = recipe.source_url
        if time_value:
            payload["time"] = time_value
        if recipe.prep_time:
            payload["prep_time"] = recipe.prep_time
        if recipe.cook_time:
            payload["cook_time"] = recipe.cook_time

        # Try yields as integer if possible, otherwise skip
        if recipe.servings:
            try:
                # Extract just the number from "6 servings"
                servings_str = str(recipe.servings).split()[0]
                payload["yields"] = int(servings_str)
            except (ValueError, IndexError):
                pass  # Skip if can't parse as int

        # Add ingredients as items
        if items:
            payload["items"] = items

        # Add photo URL if available
        if recipe.image_url:
            payload["photo"] = recipe.image_url

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/api/household/{household_id}/recipe",
                headers=self._get_headers(),
                json=payload
            )
            response.raise_for_status()
            return response.json()

    async def search_recipes(self, household_id: int, query: str) -> List[Dict[str, Any]]:
        """Search for recipes by name (for deduplication)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self.base_url}/api/household/{household_id}/recipe",
                headers=self._get_headers(),
                params={"search": query}
            )
            response.raise_for_status()
            return response.json()

    async def check_duplicate(self, household_id: int, title: str) -> List[Dict[str, Any]]:
        """Check if a recipe with similar title already exists."""
        # Search for recipes with the same title
        results = await self.search_recipes(household_id, title)

        # Filter for close matches (case-insensitive)
        title_lower = title.lower().strip()
        matches = []
        for recipe in results:
            recipe_name = recipe.get("name", "").lower().strip()
            # Exact match or contained within
            if recipe_name == title_lower or title_lower in recipe_name or recipe_name in title_lower:
                matches.append(recipe)

        return matches


async def kitchenowl_login(base_url: str, username: str, password: str) -> Dict[str, Any]:
    """Authenticate against KitchenOwl's native API.

    Returns session-compatible dict with access_token, refresh_token, user info.
    Raises ValueError on auth failure, RuntimeError on connection errors.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(
                f"{base_url.rstrip('/')}/api/auth",
                json={"username": username, "password": password, "device": "ko-pellet"},
            )
        except httpx.ConnectError:
            raise RuntimeError("Could not connect to KitchenOwl server")

        if response.status_code == 401:
            raise ValueError("Invalid username or password")
        if response.status_code != 200:
            logging.warning(f"KitchenOwl auth returned unexpected status {response.status_code}")
            raise RuntimeError("Authentication service error")

        data = response.json()
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        user_data = data.get("user", {})

        if not access_token:
            raise RuntimeError("KitchenOwl did not return an access token")

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_expires_at": time.time() + (14 * 60),  # 14 min (KO tokens last 15 min)
            "user": {
                "sub": str(user_data.get("id", "")),
                "name": user_data.get("name") or user_data.get("username", ""),
                "email": user_data.get("email", ""),
            },
            "auth_method": "kitchenowl",
        }


async def kitchenowl_refresh(base_url: str, refresh_token: str) -> Optional[Dict[str, Any]]:
    """Refresh KitchenOwl tokens using the refresh token.

    Returns dict with new access_token, refresh_token, and token_expires_at.
    Returns None on failure (expired refresh token, revoked session, etc).
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(
                f"{base_url.rstrip('/')}/api/auth/refresh",
                headers={"Authorization": f"Bearer {refresh_token}"},
            )
        except Exception as e:
            logging.warning(f"KitchenOwl token refresh failed: {e}")
            return None

        if response.status_code != 200:
            logging.info(f"KitchenOwl token refresh returned {response.status_code}")
            return None

        data = response.json()
        new_access = data.get("access_token")
        new_refresh = data.get("refresh_token")

        if not new_access:
            return None

        return {
            "access_token": new_access,
            "refresh_token": new_refresh or refresh_token,
            "token_expires_at": time.time() + (14 * 60),
        }


def _get_refresh_lock(session_id: str) -> asyncio.Lock:
    """Get or create a per-session lock for token refresh serialization."""
    if session_id not in _refresh_locks:
        # Evict oldest entries if we've hit the cap
        if len(_refresh_locks) >= _MAX_REFRESH_LOCKS:
            oldest = next(iter(_refresh_locks))
            del _refresh_locks[oldest]
        _refresh_locks[session_id] = asyncio.Lock()
    return _refresh_locks[session_id]


async def get_client_for_request(request: Request, auth: Optional[Dict[str, Any]] = None) -> KitchenOwlClient:
    """Get a KitchenOwl client, handling token refresh for KO auth sessions.

    For kitchenowl auth: uses session tokens with proactive refresh.
    For OIDC/forward-auth: uses long-lived token from encrypted secrets store.
    """
    from session_store import get_session, set_session

    if auth and auth.get("auth_method") == "kitchenowl":
        token = auth.get("access_token")
        expires_at = auth.get("token_expires_at", 0)

        # Proactive refresh: if token expires within 60 seconds
        if time.time() > (expires_at - 60):
            session_id = request.cookies.get("ko_pellet_auth")
            if not session_id:
                from fastapi import HTTPException
                raise HTTPException(status_code=401, detail="Session expired, please log in again")

            # Serialize refresh attempts per session to prevent token rotation races
            lock = _get_refresh_lock(session_id)
            async with lock:
                # Re-read session — another request may have already refreshed
                fresh_session = get_session(session_id)
                if fresh_session and fresh_session.get("token_expires_at", 0) > (time.time() + 60):
                    # Another request already refreshed, use updated token
                    return KitchenOwlClient(access_token=fresh_session["access_token"])

                # Still expired — do the refresh
                refresh_token = (fresh_session or auth).get("refresh_token")
                if refresh_token:
                    new_tokens = await kitchenowl_refresh(settings.kitchenowl_url, refresh_token)
                    if new_tokens:
                        updated_auth = dict(fresh_session or auth)
                        updated_auth.update(new_tokens)
                        set_session(session_id, updated_auth)
                        return KitchenOwlClient(access_token=new_tokens["access_token"])

                # Refresh failed — token family is dead
                from fastapi import HTTPException
                raise HTTPException(status_code=401, detail="Session expired, please log in again")

        return KitchenOwlClient(access_token=token)

    # OIDC or forward-auth: use long-lived token from secrets store
    token = get_secret("kitchenowl_token")
    return KitchenOwlClient(access_token=token)
