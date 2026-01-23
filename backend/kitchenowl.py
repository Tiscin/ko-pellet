import httpx
from starlette.requests import Request
from typing import Optional, Dict, Any, List
from models import Recipe, KitchenOwlStatus
from config import settings
from secrets_store import get_secret


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

        # Build description with instructions
        desc_parts = []
        if recipe.description:
            desc_parts.append(recipe.description)
        if recipe.instructions:
            steps = [f"{i}. {step}" for i, step in enumerate(recipe.instructions, 1)]
            desc_parts.append("Instructions:\n" + "\n".join(steps))
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

    async def upload_image(self, image_data: bytes, filename: str = "recipe.jpg") -> Optional[str]:
        """
        Upload an image to KitchenOwl and return the filename for use in recipes.

        Args:
            image_data: Raw image bytes
            filename: Original filename (used for extension detection)

        Returns:
            The filename to use in the recipe's photo field, or None if upload failed
        """
        # Determine content type from filename
        ext = filename.lower().split(".")[-1] if "." in filename else "jpg"
        content_type_map = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "webp": "image/webp",
        }
        content_type = content_type_map.get(ext, "image/jpeg")

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Prepare multipart form data
            files = {
                "file": (filename, image_data, content_type)
            }

            # Remove Content-Type from headers (httpx sets it for multipart)
            headers = {"Authorization": f"Bearer {self.access_token}"} if self.access_token else {}

            response = await client.post(
                f"{self.base_url}/api/upload",
                headers=headers,
                files=files
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("name") or data.get("filename")
            else:
                return None


def get_client_for_request(request: Request) -> KitchenOwlClient:
    """Get a KitchenOwl client using the token from encrypted secrets store."""
    # Use the long-lived token from encrypted secrets store
    token = get_secret("kitchenowl_token")
    return KitchenOwlClient(access_token=token)
