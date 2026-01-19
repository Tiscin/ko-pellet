import base64
import json
import logging
import re
from typing import Optional
from models import Recipe, Ingredient, ParseConfidence
from secrets_store import get_secret
from parsers.text_parser import (
    parse_text,
    EXTRACTION_PROMPT,
    _validate_parsed_data,
    _truncate_string,
)

# Vision extraction prompt
VISION_PROMPT = """Look at this image of a recipe (could be from a cookbook, handwritten card, screenshot, etc.).

Extract all the recipe information you can see and return it as JSON.

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
- If text is hard to read, do your best to interpret it
"""


async def parse_with_anthropic_vision(image_data: bytes, mime_type: str) -> dict:
    """Parse recipe image using Anthropic Claude Vision (async)."""
    import anthropic

    api_key = get_secret("anthropic_api_key")
    if not api_key:
        raise ValueError("Anthropic API key not configured")

    client = anthropic.AsyncAnthropic(api_key=api_key)

    # Encode image to base64
    b64_image = base64.standard_b64encode(image_data).decode("utf-8")

    message = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": b64_image,
                        },
                    },
                    {
                        "type": "text",
                        "text": VISION_PROMPT
                    }
                ],
            }
        ]
    )

    response_text = message.content[0].text

    # Extract JSON from response
    json_match = re.search(r"\{[\s\S]*\}", response_text)
    if json_match:
        return json.loads(json_match.group())
    raise ValueError("Could not extract JSON from AI response")


async def parse_with_openai_vision(image_data: bytes, mime_type: str) -> dict:
    """Parse recipe image using OpenAI Vision (async)."""
    from openai import AsyncOpenAI

    api_key = get_secret("openai_api_key")
    if not api_key:
        raise ValueError("OpenAI API key not configured")

    client = AsyncOpenAI(api_key=api_key)

    # Encode image to base64
    b64_image = base64.standard_b64encode(image_data).decode("utf-8")

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{b64_image}"
                        }
                    },
                    {
                        "type": "text",
                        "text": VISION_PROMPT
                    }
                ],
            }
        ],
        max_tokens=4096,
    )

    response_text = response.choices[0].message.content

    # Extract JSON from response
    json_match = re.search(r"\{[\s\S]*\}", response_text)
    if json_match:
        return json.loads(json_match.group())
    raise ValueError("Could not extract JSON from AI response")


async def parse_with_tesseract(image_data: bytes) -> str:
    """Extract text from image using Tesseract OCR (runs in thread pool)."""
    import asyncio
    import pytesseract
    from PIL import Image
    import io

    def _ocr_sync(data: bytes) -> str:
        image = Image.open(io.BytesIO(data))
        # Convert to RGB if necessary
        if image.mode != "RGB":
            image = image.convert("RGB")
        return pytesseract.image_to_string(image)

    # Run blocking OCR in thread pool to avoid blocking event loop
    return await asyncio.to_thread(_ocr_sync, image_data)


async def parse_image(image_data: bytes, mime_type: str = "image/jpeg") -> Recipe:
    """Parse recipe from image using vision AI or OCR fallback."""
    fields_needing_review = []
    confidence = ParseConfidence.MEDIUM

    data = None

    # Try vision AI first (preferred for images)
    anthropic_key = get_secret("anthropic_api_key")
    if anthropic_key:
        try:
            data = await parse_with_anthropic_vision(image_data, mime_type)
            confidence = ParseConfidence.HIGH
        except Exception as e:
            logging.warning(f"Anthropic vision parsing failed: {e}")

    openai_key = get_secret("openai_api_key")
    if data is None and openai_key:
        try:
            data = await parse_with_openai_vision(image_data, mime_type)
            confidence = ParseConfidence.HIGH
        except Exception as e:
            logging.warning(f"OpenAI vision parsing failed: {e}")

    # Fallback to OCR + text parsing
    if data is None:
        try:
            text = await parse_with_tesseract(image_data)
            if text.strip():
                # Use text parser on OCR output (includes its own validation)
                return await parse_text(text)
            else:
                raise ValueError("OCR extracted no text from image")
        except Exception as e:
            raise ValueError(
                f"Could not parse image. Please configure an AI API key (Anthropic or OpenAI) "
                f"for best results, or ensure Tesseract is installed for OCR fallback. Error: {e}"
            )

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

    # Images often need review
    if not data.get("title"):
        fields_needing_review.append("title")

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
