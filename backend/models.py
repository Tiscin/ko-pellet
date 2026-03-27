from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


class Ingredient(BaseModel):
    quantity: Optional[str] = None
    unit: Optional[str] = None
    name: str
    note: Optional[str] = None
    raw: Optional[str] = None  # Original text before parsing
    optional: bool = False  # False = regular ingredient, True = optional


class ParseConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Recipe(BaseModel):
    title: str
    description: Optional[str] = None
    prep_time: Optional[int] = None  # minutes
    cook_time: Optional[int] = None  # minutes
    total_time: Optional[int] = None  # minutes
    servings: Optional[str] = None
    ingredients: List[Ingredient] = Field(default_factory=list)
    instructions: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    source_url: Optional[str] = None
    notes: Optional[str] = None
    image_url: Optional[str] = None

    # Parsing metadata
    confidence: ParseConfidence = ParseConfidence.MEDIUM
    fields_needing_review: List[str] = Field(default_factory=list)
    source_type: Optional[str] = None  # url, image, text - for stats tracking


class ParseRequest(BaseModel):
    url: Optional[str] = None
    text: Optional[str] = None


class KitchenOwlStatus(BaseModel):
    connected: bool
    url: str
    error: Optional[str] = None


class RecipeCreateRequest(BaseModel):
    """Request model for creating a recipe."""
    recipe: Recipe
