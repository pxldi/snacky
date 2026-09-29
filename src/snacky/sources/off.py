"""Open Food Facts, for packaged products."""

from __future__ import annotations

import httpx

from snacky.model import FoodCandidate


class OffClient:
    def __init__(
        self,
        user_agent: str,
        base_url: str = "https://world.openfoodfacts.org",
        http: httpx.AsyncClient | None = None,
    ) -> None:
        raise NotImplementedError

    async def by_barcode(self, barcode: str) -> FoodCandidate | None:
        """None when the product is unknown or has no per-100 g energy and protein."""
        raise NotImplementedError

    async def search(self, query: str, limit: int = 10) -> list[FoodCandidate]:
        """Products sold in Germany first, German names where they exist."""
        raise NotImplementedError

    async def aclose(self) -> None:
        raise NotImplementedError
