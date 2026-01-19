# ko-pellet

Recipe import tool for [KitchenOwl](https://kitchenowl.org/). Snap a photo, paste a URL, or drop in text - ko-pellet parses it and sends it straight to your KitchenOwl instance.

## Features

- **Multiple Import Methods**
  - URL import with schema.org/Recipe parsing
  - Image upload with AI-powered OCR (mobile camera support)
  - Text paste with AI parsing

- **Security-First Design**
  - OIDC authentication (Keycloak, Authentik, Authelia)
  - Forward-auth support for reverse proxy setups
  - Encrypted secret storage (API keys stored with AES-256-GCM)
  - No secrets in environment variables after initial setup

- **Stats Dashboard**
  - Track recipes imported, success rate, time saved
  - Source breakdown (URL vs Image vs Text)
  - Owl-themed achievement badges
  - Environmental impact (paper/ink saved)

- **Enterprise Ready**
  - Custom CA certificate support for internal PKI
  - Docker volume persistence
  - Health check endpoint

## Quick Start

### 1. Clone and Configure

```bash
git clone https://github.com/youruser/ko-pellet.git
cd ko-pellet
cp .env.example .env
```

Edit `.env` with your settings:

```env
# Required
KITCHENOWL_URL=https://kitchenowl.example.com

# OIDC Authentication (option 1)
OIDC_ISSUER=https://keycloak.example.com/realms/myrealm
OIDC_CLIENT_ID=ko-pellet
OIDC_CLIENT_SECRET=your-client-secret

# App URL (for OIDC redirect)
# Default port is 8998
APP_URL=https://recipes.example.com
```

### 2. Run with Docker Compose

```bash
docker compose up -d
```

### 3. First-Time Setup

1. Navigate to your ko-pellet URL
2. Log in via OIDC
3. Complete the setup wizard:
   - Enter your KitchenOwl long-lived API token (from KitchenOwl → Profile → Sessions → click "+" in Long-lived tokens)
   - Optionally add an Anthropic API key for AI parsing
4. Select your default household in Settings

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `KITCHENOWL_URL` | Yes | URL of your KitchenOwl instance |
| `OIDC_ISSUER` | Yes* | OIDC provider URL |
| `OIDC_CLIENT_ID` | Yes* | OIDC client ID |
| `OIDC_CLIENT_SECRET` | Yes* | OIDC client secret |
| `APP_URL` | Yes | Public URL of ko-pellet (for redirects) |
| `FORWARD_AUTH_ENABLED` | No | Set `true` for forward-auth mode |
| `FORWARD_AUTH_HEADER_USER` | No | Header containing username (default: `Remote-User`) |
| `TRUSTED_PROXY_IPS` | No | Comma-separated IPs allowed to set forwarded headers (see Security section) |
| `SECRET_KEY` | No | Session secret (auto-generated if not set) |
| `ALLOWED_INTERNAL_HOSTS` | No | Comma-separated hostnames/IPs allowed for recipe URL imports (e.g., `recipes.local,ko.lan`) |
| `DEBUG` | No | Enable debug mode |

*Required unless using forward-auth mode

### Secrets (Configured via Web UI)

After logging in, configure these in Settings → API Keys:

- **KitchenOwl Token**: Long-lived API token (found in KitchenOwl → Profile → Sessions → Long-lived tokens)
- **Anthropic API Key**: For AI-powered image/text parsing
- **OpenAI API Key**: Alternative AI provider

Secrets are encrypted with AES-256-GCM and stored in `/data/secrets.json`.

### Custom CA Certificates

For environments using internal/private CAs:

```bash
mkdir certs
cp /path/to/your-ca.crt certs/
docker compose up -d
```

On startup, ko-pellet automatically builds a combined CA bundle from all `.crt` files in `./certs/`.

## Authentication Methods

### OIDC (Recommended)

Configure your OIDC provider (Keycloak, Authentik, etc.) with:

- **Redirect URI**: `https://your-ko-pellet-url/api/auth/callback`
- **Scopes**: `openid`, `profile`, `email`

### Forward-Auth

For reverse proxies with built-in auth (Authelia, Authentik proxy):

```env
FORWARD_AUTH_ENABLED=true
FORWARD_AUTH_HEADER_USER=Remote-User
```

ko-pellet reads the authenticated user from proxy headers.

## API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/health` | No | Health check |
| GET | `/api/auth/status` | No | Authentication status |
| GET | `/api/auth/login` | No | Initiate OIDC login |
| GET | `/api/auth/callback` | No | OIDC callback |
| POST | `/api/auth/logout` | Yes | Logout |
| GET | `/api/secrets/status` | Yes | Check configured secrets |
| POST | `/api/secrets/{key}` | Yes | Set a secret |
| DELETE | `/api/secrets/{key}` | Yes | Delete a secret |
| POST | `/api/parse/url` | Yes | Parse recipe from URL |
| POST | `/api/parse/text` | Yes | Parse recipe from text |
| POST | `/api/parse/image` | Yes | Parse recipe from image |
| GET | `/api/kitchenowl/status` | No | KitchenOwl connection status |
| GET | `/api/kitchenowl/households` | Yes | List households |
| POST | `/api/kitchenowl/recipe/{id}` | Yes | Create recipe |
| GET | `/api/stats` | Yes | Get usage statistics |

## Development

### Local Setup

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload

# Frontend is served by the backend
```

### Project Structure

```
ko-pellet/
├── backend/
│   ├── main.py           # FastAPI application
│   ├── auth.py           # OIDC authentication
│   ├── forward_auth.py   # Forward-auth support
│   ├── config.py         # Settings management
│   ├── crypto.py         # AES-256-GCM encryption
│   ├── secrets_store.py  # Encrypted secrets storage
│   ├── session_store.py  # File-based sessions
│   ├── stats_store.py    # SQLite stats tracking
│   ├── kitchenowl.py     # KitchenOwl API client
│   ├── models.py         # Pydantic models
│   ├── entrypoint.sh     # Container entrypoint (CA handling)
│   └── parsers/
│       ├── url_parser.py    # Schema.org recipe parsing
│       ├── text_parser.py   # AI text parsing
│       └── image_parser.py  # AI image parsing
├── frontend/
│   ├── index.html        # Single-page app
│   ├── app.js            # Frontend logic
│   └── styles.css        # Styling
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Security Considerations

- **Secrets**: API keys are encrypted at rest using AES-256-GCM with a device key stored in `/data/.device_key`
- **Sessions**: File-based sessions in `/data/sessions/` with 0600 permissions
- **Cookies**: `Secure` and `HttpOnly` flags set automatically when `APP_URL` uses HTTPS
- **CSRF Protection**: Origin header verified on state-changing endpoints (secrets mutations)
- **OIDC**: State parameter validated to prevent CSRF
- **Container**: Runs as non-root user (uid 1000)
- **Data Directory**: Permissions set to 700
- **Rate Limiting**: API endpoints are rate-limited to prevent abuse
- **SSRF Protection**: Recipe URL imports block private IP ranges (configurable allowlist via `ALLOWED_INTERNAL_HOSTS`)

### Network Security

By default, `docker-compose.yml` exposes port 8998 on all interfaces. For production deployments behind a reverse proxy, consider restricting access:

**Option 1: Bind to specific IP** (proxy on different host)
```yaml
ports:
  - "192.168.1.50:8998:8000"  # Only accessible via this host's LAN IP
```

**Option 2: Localhost only** (proxy on same host)
```yaml
ports:
  - "127.0.0.1:8998:8000"  # Only accessible from the same machine
```

**Option 3: Docker network only** (proxy in same Docker environment)
```yaml
# Remove the ports section entirely and use Docker networks
networks:
  - traefik
```

When using OIDC authentication, exposing the port is less risky since authentication still requires a valid OIDC login. However, restricting network access adds defense-in-depth.

### Forward-Auth Security

When using forward-auth mode (`FORWARD_AUTH_ENABLED=true`), authentication is delegated to your reverse proxy (Authelia, Authentik, etc.). The proxy sets headers like `Remote-User` to identify the authenticated user.

**Important**: Forward-auth relies on network-level security. If someone can reach the ko-pellet container directly (bypassing the proxy), they could spoof these headers and impersonate any user.

**Required setup**:

1. Ensure the container is only accessible through your reverse proxy (use Docker networks, firewall rules, etc.)
2. Configure `TRUSTED_PROXY_IPS` with your proxy's IP or CIDR:

```env
# Single IP
TRUSTED_PROXY_IPS=172.17.0.1

# CIDR for Docker network
TRUSTED_PROXY_IPS=172.18.0.0/16

# Multiple entries
TRUSTED_PROXY_IPS=192.168.1.1,10.0.0.0/8
```

**Security behavior**:
- `TRUSTED_PROXY_IPS` is **required** when `FORWARD_AUTH_ENABLED=true`
- If not set, forward-auth will **reject all authentication attempts** (fail-closed)
- A clear error is logged at startup if misconfigured
- Only requests from trusted IPs/CIDRs will have auth headers and `X-Forwarded-For` trusted

## Badges

Earn owl-themed badges as you import recipes:

| Recipes | Badge | Description |
|---------|-------|-------------|
| 10 | Owlet | Just hatched into the recipe world |
| 20 | Fledgling | Learning to spread your wings |
| 30 | Night Hunter | Sharp eyes for finding recipes |
| 50 | Great Horned | An impressive collection grows |
| 100 | Parliament Leader | Leading the flock |
| 200 | Grand Parliament | A true recipe dynasty |
| 500 | Cosmic Owl | Transcended mortal cooking |
| 1000 | Owl Singularity | You ARE the cookbook |

## License

MIT

## Acknowledgments

- [KitchenOwl](https://kitchenowl.org/) - The excellent self-hosted recipe manager
- [Anthropic Claude](https://anthropic.com/) - AI-powered recipe parsing
