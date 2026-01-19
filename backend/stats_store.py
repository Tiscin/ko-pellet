"""Stats storage using SQLite for persistence."""

import sqlite3
import json
import os
from datetime import datetime
from typing import Dict, Any, Optional, List
from config import settings

DB_PATH = os.path.join(settings.data_dir, "stats.db")

# Owl-themed badges for every 10 recipes
OWL_BADGES = {
    10: ("Owlet", "Just hatched into the recipe world"),
    20: ("Fledgling", "Learning to spread your wings"),
    30: ("Night Hunter", "Sharp eyes for finding recipes"),
    40: ("Wise Owl", "Gaining culinary wisdom"),
    50: ("Great Horned", "An impressive collection grows"),
    60: ("Barn Owl", "Master of the domestic kitchen"),
    70: ("Snowy Owl", "Cool, calm, collected chef"),
    80: ("Eagle Owl", "Soaring to new culinary heights"),
    90: ("Spectacled Owl", "A scholarly recipe collector"),
    100: ("Parliament Leader", "Leading the flock"),
    110: ("Tawny Sage", "Deep knowledge of flavors"),
    120: ("Screech Master", "Your recipes make people scream with joy"),
    130: ("Burrowing Chef", "Digging deep into cuisines"),
    140: ("Long-eared Legend", "Always listening for new recipes"),
    150: ("Elf Owl Elite", "Small but mighty collection"),
    160: ("Pygmy Powerhouse", "Compact but impressive"),
    170: ("Barred Boss", "No recipe bars your way"),
    180: ("Spotted Specialist", "Spotting recipes everywhere"),
    190: ("Boreal Master", "Northern star of cooking"),
    200: ("Grand Parliament", "A true recipe dynasty"),
    250: ("Mythic Strix", "Legendary status achieved"),
    300: ("Eternal Athena", "Wisdom incarnate"),
    500: ("Cosmic Owl", "Transcended mortal cooking"),
    1000: ("Owl Singularity", "You ARE the cookbook"),
}


def get_db_connection() -> sqlite3.Connection:
    """Get a database connection, creating tables if needed."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection):
    """Initialize database tables."""
    cursor = conn.cursor()

    # Main stats table (single row, updated over time)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lifetime_stats (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            total_recipes INTEGER DEFAULT 0,
            recipes_url INTEGER DEFAULT 0,
            recipes_image INTEGER DEFAULT 0,
            recipes_text INTEGER DEFAULT 0,
            recipes_abandoned INTEGER DEFAULT 0,
            ai_api_calls INTEGER DEFAULT 0,
            total_ingredients INTEGER DEFAULT 0,
            total_instructions INTEGER DEFAULT 0,
            total_confidence_sum REAL DEFAULT 0,
            total_confidence_count INTEGER DEFAULT 0,
            first_recipe_at TEXT,
            last_recipe_title TEXT,
            last_recipe_source TEXT,
            last_recipe_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Tags frequency table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tag_stats (
            tag TEXT PRIMARY KEY,
            count INTEGER DEFAULT 1
        )
    """)

    # Ensure the single stats row exists
    cursor.execute("""
        INSERT OR IGNORE INTO lifetime_stats (id) VALUES (1)
    """)

    conn.commit()


def record_parse_started(source_type: str):
    """Record that a parse was started (for tracking abandonment)."""
    # We track this by incrementing abandoned, then decrementing on save
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE lifetime_stats
            SET recipes_abandoned = recipes_abandoned + 1,
                updated_at = ?
            WHERE id = 1
        """, (datetime.utcnow().isoformat(),))
        conn.commit()
    finally:
        conn.close()


def record_ai_call():
    """Record an AI API call."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE lifetime_stats
            SET ai_api_calls = ai_api_calls + 1,
                updated_at = ?
            WHERE id = 1
        """, (datetime.utcnow().isoformat(),))
        conn.commit()
    finally:
        conn.close()


def record_recipe_saved(
    source_type: str,
    title: str,
    ingredients_count: int,
    instructions_count: int,
    confidence: str,
    tags: List[str]
):
    """Record a successfully saved recipe."""
    confidence_value = {"high": 1.0, "medium": 0.6, "low": 0.3}.get(confidence, 0.5)
    now = datetime.utcnow().isoformat()

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Get current stats to check if this is the first recipe
        cursor.execute("SELECT first_recipe_at FROM lifetime_stats WHERE id = 1")
        row = cursor.fetchone()
        first_recipe_at = row["first_recipe_at"] if row else None

        # Update source-specific counter using explicit mapping (no SQL injection risk)
        # Use separate queries to avoid f-string interpolation in SQL
        cursor.execute("""
            UPDATE lifetime_stats
            SET total_recipes = total_recipes + 1,
                recipes_abandoned = MAX(0, recipes_abandoned - 1),
                total_ingredients = total_ingredients + ?,
                total_instructions = total_instructions + ?,
                total_confidence_sum = total_confidence_sum + ?,
                total_confidence_count = total_confidence_count + 1,
                first_recipe_at = COALESCE(first_recipe_at, ?),
                last_recipe_title = ?,
                last_recipe_source = ?,
                last_recipe_at = ?,
                updated_at = ?
            WHERE id = 1
        """, (
            ingredients_count,
            instructions_count,
            confidence_value,
            now,
            title,
            source_type,
            now,
            now
        ))

        # Increment source-specific counter with explicit column selection
        if source_type == "url":
            cursor.execute("UPDATE lifetime_stats SET recipes_url = recipes_url + 1 WHERE id = 1")
        elif source_type == "image":
            cursor.execute("UPDATE lifetime_stats SET recipes_image = recipes_image + 1 WHERE id = 1")
        elif source_type == "text":
            cursor.execute("UPDATE lifetime_stats SET recipes_text = recipes_text + 1 WHERE id = 1")
        else:
            # Default to URL for unknown source types
            cursor.execute("UPDATE lifetime_stats SET recipes_url = recipes_url + 1 WHERE id = 1")

        # Update tag counts
        for tag in tags:
            tag_lower = tag.lower().strip()
            if tag_lower:
                cursor.execute("""
                    INSERT INTO tag_stats (tag, count) VALUES (?, 1)
                    ON CONFLICT(tag) DO UPDATE SET count = count + 1
                """, (tag_lower,))

        conn.commit()
    finally:
        conn.close()


def get_current_badge(total_recipes: int) -> Optional[Dict[str, str]]:
    """Get the current badge based on recipe count."""
    earned_badge = None
    for threshold in sorted(OWL_BADGES.keys(), reverse=True):
        if total_recipes >= threshold:
            name, description = OWL_BADGES[threshold]
            earned_badge = {
                "name": name,
                "description": description,
                "threshold": threshold
            }
            break
    return earned_badge


def get_next_badge(total_recipes: int) -> Optional[Dict[str, Any]]:
    """Get the next badge to earn."""
    for threshold in sorted(OWL_BADGES.keys()):
        if total_recipes < threshold:
            name, description = OWL_BADGES[threshold]
            return {
                "name": name,
                "description": description,
                "threshold": threshold,
                "recipes_needed": threshold - total_recipes
            }
    return None


def get_stats() -> Dict[str, Any]:
    """Get all lifetime stats."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Get main stats
        cursor.execute("SELECT * FROM lifetime_stats WHERE id = 1")
        row = cursor.fetchone()

        if not row:
            return {"error": "No stats found"}

        stats = dict(row)
        total_recipes = stats["total_recipes"]

        # Calculate derived stats
        # Time saved: ~15 min to manually type a recipe
        time_saved_minutes = total_recipes * 15
        stats["time_saved_minutes"] = time_saved_minutes
        stats["time_saved_hours"] = round(time_saved_minutes / 60, 1)

        # Paper saved: ~2 pages per printed recipe
        pages_saved = total_recipes * 2
        stats["pages_saved"] = pages_saved

        # Ink cartridges: ~500 pages per cartridge
        stats["ink_cartridges_saved"] = round(pages_saved / 500, 2)

        # Trees: ~8,333 pages per tree (simplified estimate)
        stats["trees_saved"] = round(pages_saved / 8333, 4)

        # Average confidence
        if stats["total_confidence_count"] > 0:
            avg_conf = stats["total_confidence_sum"] / stats["total_confidence_count"]
            stats["average_confidence"] = round(avg_conf * 100, 1)
            stats["average_confidence_label"] = (
                "high" if avg_conf >= 0.8 else "medium" if avg_conf >= 0.5 else "low"
            )
        else:
            stats["average_confidence"] = None
            stats["average_confidence_label"] = None

        # Success rate
        total_attempts = total_recipes + stats["recipes_abandoned"]
        if total_attempts > 0:
            stats["success_rate"] = round((total_recipes / total_attempts) * 100, 1)
        else:
            stats["success_rate"] = 100.0

        # Get top tags
        cursor.execute("""
            SELECT tag, count FROM tag_stats
            ORDER BY count DESC
            LIMIT 5
        """)
        stats["top_tags"] = [{"tag": row["tag"], "count": row["count"]} for row in cursor.fetchall()]

        # Badges
        stats["current_badge"] = get_current_badge(total_recipes)
        stats["next_badge"] = get_next_badge(total_recipes)

        # Clean up internal fields
        del stats["id"]
        del stats["total_confidence_sum"]
        del stats["total_confidence_count"]

        return stats

    finally:
        conn.close()


def reset_stats():
    """Reset all stats (for testing)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM lifetime_stats")
        cursor.execute("DELETE FROM tag_stats")
        cursor.execute("INSERT INTO lifetime_stats (id) VALUES (1)")
        conn.commit()
    finally:
        conn.close()
