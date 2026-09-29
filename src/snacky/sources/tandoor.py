"""Tandoor (2.6.x): recipe nutrition for logging a portion, and food
properties for filling nutrients in from BLS."""

from __future__ import annotations

import httpx

from snacky.model import RecipeNutrition


class TandoorClient:
    def __init__(self, base_url: str, token: str, http: httpx.AsyncClient | None = None) -> None:
        raise NotImplementedError

    async def recipe_nutrition(self, recipe_id: int) -> RecipeNutrition:
        """Nutrition per serving as Tandoor computes it from its food properties."""
        raise NotImplementedError

    async def aclose(self) -> None:
        raise NotImplementedError
