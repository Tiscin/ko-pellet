# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ko-pellet is a recipe import tool for KitchenOwl. It parses recipes from URLs, images (OCR), or text using AI, then sends them to a KitchenOwl instance.

## Development Commands

```bash
# Local development with hot reload
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload

# Production via Docker
docker compose up -d
```

The frontend is static HTML/CSS/JS served by FastAPI's StaticFiles mount at `/` - no separate build step needed.

## Architecture

**Backend (Python/FastAPI)** - `backend/`
- `main.py` - FastAPI app, all route definitions, rate limiting setup
- `auth.py` - OIDC authentication via Authlib
- `forward_auth.py` - Alternative auth via reverse proxy headers
- `config.py` - Pydantic Settings configuration with SSRF protection
- `secrets_store.py` - AES-256-GCM encrypted secret storage (API keys)
- `session_store.py` - File-based session management
- `stats_store.py` - SQLite-backed usage statistics and badge tracking
- `kitchenowl.py` - KitchenOwl API client (households, recipe creation)
- `parsers/` - Recipe parsing implementations:
  - `url_parser.py` - schema.org/Recipe extraction with SSRF protection
  - `text_parser.py` - Claude/OpenAI text parsing
  - `image_parser.py` - Tesseract OCR + AI vision

**Frontend** - `frontend/`
- Vanilla JavaScript SPA (no framework)
- `app.js` handles all state management and API interactions
- Tab interface for URL/Image/Text parsing modes

## Key Patterns

- **Two auth modes**: OIDC (standard) or forward-auth (reverse proxy). Controlled by `FORWARD_AUTH_ENABLED` env var.
- **Secrets via web UI**: API keys (KitchenOwl token, Anthropic, OpenAI) are configured in-app and stored encrypted in `/data/secrets.json`, not in env vars.
- **Parsing confidence**: All parsers return `ParseConfidence` (HIGH/MEDIUM/LOW) to flag fields needing review.
- **Rate limiting**: Applied to `/api/parse/*` endpoints via slowapi.
- **SSRF protection**: URL parser blocks private IP ranges; allowlist via `ALLOWED_INTERNAL_HOSTS`.

## Data Storage

All persistent data lives in `/data/` (Docker volume `ko-pellet-data`):
- `secrets.json` - Encrypted API credentials
- `.device_key` - Encryption key (auto-generated)
- `sessions/` - User session files
- `stats.db` - SQLite statistics database
