"""Simple file-based session store to handle large session data (JWT tokens)."""

import json
import os
import time
import uuid
import hashlib
from typing import Optional, Dict, Any
from pathlib import Path


def _get_session_dir() -> Path:
    """Get the session directory from config."""
    from config import settings
    return Path(settings.data_dir) / "sessions"


SESSION_MAX_AGE = 86400 * 7  # 7 days


def _get_session_path(session_id: str) -> Path:
    """Get the file path for a session."""
    # Use hash to prevent directory traversal
    safe_id = hashlib.sha256(session_id.encode()).hexdigest()
    return _get_session_dir() / f"{safe_id}.json"


def init_session_store():
    """Initialize the session store directory with restricted permissions."""
    session_dir = _get_session_dir()
    session_dir.mkdir(parents=True, exist_ok=True)
    # Set restricted permissions
    try:
        session_dir.chmod(0o700)
    except (OSError, IOError):
        pass  # May fail if directory already exists with different owner


def _write_session_file(session_path: Path, data: dict):
    """Write session data to file with restricted permissions."""
    session_path.write_text(json.dumps(data))
    try:
        session_path.chmod(0o600)
    except (OSError, IOError):
        pass  # Best effort


def create_session() -> str:
    """Create a new session and return its ID."""
    init_session_store()
    session_id = str(uuid.uuid4())
    session_path = _get_session_path(session_id)
    session_data = {
        "created_at": time.time(),
        "data": {}
    }
    _write_session_file(session_path, session_data)
    return session_id


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Get session data by ID."""
    if not session_id:
        return None

    session_path = _get_session_path(session_id)
    if not session_path.exists():
        return None

    try:
        session_data = json.loads(session_path.read_text())

        # Check if session is expired
        created_at = session_data.get("created_at", 0)
        if time.time() - created_at > SESSION_MAX_AGE:
            session_path.unlink(missing_ok=True)
            return None

        return session_data.get("data", {})
    except (json.JSONDecodeError, IOError):
        return None


def set_session(session_id: str, data: Dict[str, Any]):
    """Set session data."""
    init_session_store()
    session_path = _get_session_path(session_id)

    # Load existing session or create new
    if session_path.exists():
        try:
            session_data = json.loads(session_path.read_text())
        except (json.JSONDecodeError, IOError):
            session_data = {"created_at": time.time(), "data": {}}
    else:
        session_data = {"created_at": time.time(), "data": {}}

    session_data["data"] = data
    _write_session_file(session_path, session_data)


def delete_session(session_id: str):
    """Delete a session."""
    if not session_id:
        return
    session_path = _get_session_path(session_id)
    session_path.unlink(missing_ok=True)


def cleanup_expired_sessions():
    """Remove expired sessions."""
    session_dir = _get_session_dir()
    if not session_dir.exists():
        return

    now = time.time()
    for session_file in session_dir.glob("*.json"):
        try:
            session_data = json.loads(session_file.read_text())
            created_at = session_data.get("created_at", 0)
            if now - created_at > SESSION_MAX_AGE:
                session_file.unlink()
        except (json.JSONDecodeError, IOError):
            session_file.unlink(missing_ok=True)
