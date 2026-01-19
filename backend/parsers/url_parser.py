import httpx
import ipaddress
import socket
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from recipe_scrapers import scrape_html
from typing import Optional, Set
from models import Recipe, Ingredient, ParseConfidence
from config import settings


# Private/internal IP ranges to block (SSRF protection)
BLOCKED_IP_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local / cloud metadata
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),  # IPv6 localhost
    ipaddress.ip_network("fc00::/7"),  # IPv6 private
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]


def get_allowed_internal_hosts() -> Set[str]:
    """Get the set of allowed internal hosts from config."""
    if not settings.allowed_internal_hosts:
        return set()
    return {h.strip().lower() for h in settings.allowed_internal_hosts.split(",") if h.strip()}


def is_host_allowed(hostname: str) -> bool:
    """Check if a hostname is in the allowlist."""
    allowed = get_allowed_internal_hosts()
    if not allowed:
        return False
    return hostname.lower() in allowed


def validate_url(url: str) -> None:
    """Validate URL to prevent SSRF attacks."""
    parsed = urlparse(url)

    # Only allow http/https schemes
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid URL scheme: {parsed.scheme}. Only http/https allowed.")

    # Must have a hostname
    if not parsed.hostname:
        raise ValueError("Invalid URL: no hostname")

    hostname_lower = parsed.hostname.lower()

    # Check if hostname is in allowlist (skip all other checks if allowed)
    if is_host_allowed(hostname_lower):
        return

    # Block common dangerous hostnames (cloud metadata, etc.)
    dangerous_hostnames = [
        "metadata.google.internal", "metadata.gcp.internal",
        "instance-data", "kubernetes.default",
    ]
    if hostname_lower in dangerous_hostnames:
        raise ValueError(f"Blocked hostname: {parsed.hostname}")

    # Resolve hostname and check IP
    try:
        resolved_ips = socket.getaddrinfo(parsed.hostname, None, socket.AF_UNSPEC)
        for family, _, _, _, sockaddr in resolved_ips:
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
                for blocked_range in BLOCKED_IP_RANGES:
                    if ip in blocked_range:
                        raise ValueError(f"URL resolves to private IP range. Add '{parsed.hostname}' to ALLOWED_INTERNAL_HOSTS to allow.")
            except ValueError as e:
                if "private IP" in str(e) or "ALLOWED_INTERNAL_HOSTS" in str(e):
                    raise
                # Invalid IP format, skip
                continue
    except socket.gaierror as e:
        raise ValueError(f"Could not resolve hostname: {parsed.hostname}")


async def parse_url(url: str) -> Recipe:
    """Parse a recipe from a URL using recipe-scrapers library."""
    # Validate URL to prevent SSRF
    validate_url(url)

    # Fetch the page (disable redirects to prevent SSRF via redirect)
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        response = await client.get(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; ko-pellet/1.0; recipe importer)"
        })

        # Handle redirects manually with validation
        redirect_count = 0
        while response.is_redirect and redirect_count < 5:
            redirect_url = response.headers.get("location")
            if not redirect_url:
                break
            # Make absolute if relative
            if not redirect_url.startswith(("http://", "https://")):
                parsed_orig = urlparse(url)
                redirect_url = f"{parsed_orig.scheme}://{parsed_orig.netloc}{redirect_url}"
            # Validate redirect target
            validate_url(redirect_url)
            response = await client.get(redirect_url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; ko-pellet/1.0; recipe importer)"
            })
            redirect_count += 1

        response.raise_for_status()
        html = response.text

    # Try recipe-scrapers first
    try:
        scraper = scrape_html(html, org_url=url)

        # Parse ingredients
        ingredients = []
        for ing_str in scraper.ingredients():
            ingredients.append(Ingredient(
                name=ing_str,
                raw=ing_str,
            ))

        # Get times
        prep_time = None
        cook_time = None
        total_time = None

        try:
            total_time = scraper.total_time()
        except Exception:
            pass

        try:
            prep_time = scraper.prep_time()
        except Exception:
            pass

        try:
            cook_time = scraper.cook_time()
        except Exception:
            pass

        # Get yields/servings
        servings = None
        try:
            servings = scraper.yields()
        except Exception:
            pass

        # Get image
        image_url = None
        try:
            image_url = scraper.image()
        except Exception:
            pass

        return Recipe(
            title=scraper.title(),
            description=scraper.description() if hasattr(scraper, 'description') else None,
            prep_time=prep_time,
            cook_time=cook_time,
            total_time=total_time,
            servings=servings,
            ingredients=ingredients,
            instructions=scraper.instructions_list(),
            tags=[],
            source_url=url,
            image_url=image_url,
            confidence=ParseConfidence.HIGH,
            fields_needing_review=[],
        )
    except Exception as e:
        # Fall back to basic HTML parsing
        print(f"recipe-scrapers failed: {e}, falling back to basic parsing")
        return await _parse_html_fallback(html, url)


async def _parse_html_fallback(html: str, url: str) -> Recipe:
    """Basic fallback HTML parsing when recipe-scrapers fails."""
    soup = BeautifulSoup(html, 'html.parser')

    # Try to find title
    title = "Untitled Recipe"
    for selector in ['h1', '.recipe-title', '[itemprop="name"]', 'title']:
        el = soup.select_one(selector)
        if el:
            title = el.get_text(strip=True)
            break

    # Try to find ingredients
    ingredients = []
    for selector in ['.ingredients li', '[itemprop="recipeIngredient"]', '.ingredient']:
        els = soup.select(selector)
        if els:
            for el in els:
                text = el.get_text(strip=True)
                if text:
                    ingredients.append(Ingredient(name=text, raw=text))
            break

    # Try to find instructions
    instructions = []
    for selector in ['.instructions li', '[itemprop="recipeInstructions"]', '.instruction', '.step']:
        els = soup.select(selector)
        if els:
            for el in els:
                text = el.get_text(strip=True)
                if text:
                    instructions.append(text)
            break

    return Recipe(
        title=title,
        ingredients=ingredients,
        instructions=instructions,
        source_url=url,
        confidence=ParseConfidence.LOW,
        fields_needing_review=["title", "ingredients", "instructions"],
    )
