import json
import logging
import re
from typing import Optional
from models import Recipe, Ingredient, ParseConfidence
from secrets_store import get_secret

# Output validation limits to prevent excessive data from AI responses
MAX_INGREDIENTS = 200
MAX_INSTRUCTIONS = 100
MAX_TAGS = 50
MAX_FIELD_LENGTH = 10000  # 10KB per text field

# AI extraction prompt
EXTRACTION_PROMPT = """Extract the recipe information from the following text and return it as JSON.

Parse the recipe into this exact structure:
{
  "title": "Recipe name",
  "description": "Brief description if available",
  "prep_time": null or number in minutes,
  "cook_time": null or number in minutes,
  "total_time": null or number in minutes,
  "servings": "yield string like '4 servings' or '12 cookies'",
  "ingredients": [
    {"quantity": "1", "unit": "cup", "name": "flour", "note": "sifted"},
    ...
  ],
  "instructions": ["Step 1...", "Step 2...", ...],
  "tags": ["category1", "category2"],
  "notes": "Any additional notes"
}

Rules:
- For ingredients, separate quantity (numbers/fractions), unit (cup, tbsp, etc), and name
- If no unit, leave it null
- Notes in ingredients are things in parentheses like "(optional)" or "(divided)"
- Instructions should be separate steps, not one big block
- Tags should be relevant categories like "dessert", "vegetarian", "quick", etc.
- Times should be converted to minutes (1 hour = 60)
- Return ONLY valid JSON, no markdown or explanation

Recipe text:
"""


async def parse_with_anthropic(text: str) -> dict:
    """Parse recipe text using Anthropic Claude (async)."""
    import anthropic

    api_key = get_secret("anthropic_api_key")
    if not api_key:
        raise ValueError("Anthropic API key not configured")

    client = anthropic.AsyncAnthropic(api_key=api_key)

    message = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[
            {"role": "user", "content": EXTRACTION_PROMPT + text}
        ]
    )

    response_text = message.content[0].text

    # Extract JSON from response
    json_match = re.search(r"\{[\s\S]*\}", response_text)
    if json_match:
        return json.loads(json_match.group())
    raise ValueError("Could not extract JSON from AI response")


async def parse_with_openai(text: str) -> dict:
    """Parse recipe text using OpenAI (async)."""
    from openai import AsyncOpenAI

    api_key = get_secret("openai_api_key")
    if not api_key:
        raise ValueError("OpenAI API key not configured")

    client = AsyncOpenAI(api_key=api_key)

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "user", "content": EXTRACTION_PROMPT + text}
        ],
        response_format={"type": "json_object"}
    )

    return json.loads(response.choices[0].message.content)


def _truncate_string(s: str, max_len: int = MAX_FIELD_LENGTH) -> str:
    """Truncate a string to max length."""
    if s and len(s) > max_len:
        return s[:max_len] + "..."
    return s


def _validate_parsed_data(data: dict) -> dict:
    """Validate and limit parsed data to prevent excessive output."""
    # Limit ingredients
    if "ingredients" in data and len(data["ingredients"]) > MAX_INGREDIENTS:
        logging.warning(f"Truncating ingredients from {len(data['ingredients'])} to {MAX_INGREDIENTS}")
        data["ingredients"] = data["ingredients"][:MAX_INGREDIENTS]

    # Limit instructions
    if "instructions" in data and len(data["instructions"]) > MAX_INSTRUCTIONS:
        logging.warning(f"Truncating instructions from {len(data['instructions'])} to {MAX_INSTRUCTIONS}")
        data["instructions"] = data["instructions"][:MAX_INSTRUCTIONS]

    # Limit tags
    if "tags" in data and len(data["tags"]) > MAX_TAGS:
        data["tags"] = data["tags"][:MAX_TAGS]

    # Truncate string fields
    for field in ["title", "description", "notes", "servings"]:
        if field in data and data[field]:
            data[field] = _truncate_string(str(data[field]))

    # Truncate instruction strings
    if "instructions" in data:
        data["instructions"] = [_truncate_string(str(i)) for i in data["instructions"]]

    return data


def parse_manually(text: str) -> dict:
    """Basic manual parsing as fallback."""
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]

    if not lines:
        raise ValueError("No text provided")

    # First non-empty line is likely the title
    title = lines[0]

    # Try to identify ingredients vs instructions
    ingredients = []
    instructions = []
    in_ingredients = False
    in_instructions = False

    ingredient_markers = ["ingredients", "you'll need", "you will need", "what you need"]
    instruction_markers = ["instructions", "directions", "method", "steps", "preparation"]

    for line in lines[1:]:
        lower = line.lower()

        # Check for section headers
        if any(m in lower for m in ingredient_markers):
            in_ingredients = True
            in_instructions = False
            continue
        if any(m in lower for m in instruction_markers):
            in_ingredients = False
            in_instructions = True
            continue

        # Heuristics for ingredients vs instructions
        # Ingredients typically start with numbers/fractions or are short
        looks_like_ingredient = (
            re.match(r"^[\d\u00bc-\u00be\u2150-\u215e]", line) or  # starts with number/fraction
            (len(line) < 50 and not line.endswith(".")) or
            line.startswith("-") or
            line.startswith("*") or
            line.startswith("•")
        )

        if in_ingredients or (not in_instructions and looks_like_ingredient and len(line) < 80):
            # Clean up bullet points
            clean = re.sub(r"^[-*•]\s*", "", line)
            if clean:
                ingredients.append({"name": clean, "raw": clean})
        elif in_instructions or line.endswith(".") or len(line) > 50:
            # Clean up step numbers
            clean = re.sub(r"^\d+[\.\)]\s*", "", line)
            if clean:
                instructions.append(clean)

    return {
        "title": title,
        "ingredients": ingredients,
        "instructions": instructions,
    }


async def parse_text(text: str) -> Recipe:
    """Parse recipe from plain text using AI or fallback to manual parsing."""
    fields_needing_review = []
    confidence = ParseConfidence.MEDIUM

    data = None

    # Try AI parsing first
    anthropic_key = get_secret("anthropic_api_key")
    if anthropic_key:
        try:
            data = await parse_with_anthropic(text)
            confidence = ParseConfidence.HIGH
        except Exception as e:
            logging.warning(f"Anthropic parsing failed: {e}")

    openai_key = get_secret("openai_api_key")
    if data is None and openai_key:
        try:
            data = await parse_with_openai(text)
            confidence = ParseConfidence.HIGH
        except Exception as e:
            logging.warning(f"OpenAI parsing failed: {e}")

    if data is None:
        # Fallback to manual parsing
        data = parse_manually(text)
        confidence = ParseConfidence.LOW
        fields_needing_review = ["ingredients", "instructions"]

    # Validate and limit output
    data = _validate_parsed_data(data)

    # Convert to Recipe model
    ingredients = []
    for ing in data.get("ingredients", []):
        if isinstance(ing, dict):
            ingredients.append(Ingredient(
                quantity=ing.get("quantity"),
                unit=ing.get("unit"),
                name=_truncate_string(ing.get("name", ""), 500),
                note=ing.get("note"),
                raw=ing.get("raw"),
            ))
        else:
            ingredients.append(Ingredient(
                name=_truncate_string(str(ing), 500),
                raw=_truncate_string(str(ing), 500)
            ))

    return Recipe(
        title=data.get("title", "Untitled Recipe"),
        description=data.get("description"),
        prep_time=data.get("prep_time"),
        cook_time=data.get("cook_time"),
        total_time=data.get("total_time"),
        servings=data.get("servings"),
        ingredients=ingredients,
        instructions=data.get("instructions", []),
        tags=data.get("tags", []),
        notes=data.get("notes"),
        confidence=confidence,
        fields_needing_review=fields_needing_review,
    )
