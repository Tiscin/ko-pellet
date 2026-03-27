# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.1.0] - 2026-03-27

### Fixed

- **Ingredients imported as single string** — KitchenOwl received the full ingredient text (e.g., "70g Onions") as the item name instead of splitting into name and description. Ingredient rows now have three editable columns (Amount, Ingredient, Note) so quantity/unit are sent as the KitchenOwl `description` field and the ingredient name stands alone.
- **Ingredients imported as optional** — all ingredients defaulted to "Optional" in KitchenOwl, requiring manual selection before adding to shopping list. Now explicitly sets `optional: false` so ingredients import as regular items.

### Added

- **Structured ingredient editing** — parsed ingredients display in separate Amount, Ingredient, and Note columns with column headers. Users can review and correct the split before importing.
- **Client-side ingredient parser** — raw ingredient strings are automatically split into quantity/unit and name using pattern matching (handles "2 cups flour", "70g Onions", "3 Tomatoes", etc.).
- **Duplicate recipe detection** — checks for existing recipes with similar titles before saving and prompts for confirmation.

## [1.0.0] - 2026-03-14

### Added

- Initial release
- Parse recipes from URLs (schema.org/Recipe extraction)
- Parse recipes from images (Tesseract OCR + AI vision)
- Parse recipes from pasted text (Claude/OpenAI)
- Import to KitchenOwl via API
- Three auth modes: OIDC, forward-auth (reverse proxy), KitchenOwl native login
- AES-256-GCM encrypted secret storage for API keys
- Setup wizard for first-run configuration
- Usage statistics and achievement badges
- Dark/light theme
- SSRF protection on URL parser
- Rate limiting on parse endpoints
