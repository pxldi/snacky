"""Open Food Facts, for packaged products.

What the docs say today (checked 2026-09, openfoodfacts-server docs/api):

- Barcode: `GET /api/v2/product/<barcode>.json?fields=...`. An unknown code
  answers 404 with `status: 0`.
- Text search: v2 and v3 have no full-text search, and the legacy
  `/cgi/search.pl` answered 503 when checked. This client uses Search-a-licious
  (https://search.openfoodfacts.org/docs): `GET /search` with `q`, `langs`,
  `page_size` and `fields`, and a filter written inside `q` as
  `fieldname:"value"`, e.g. `countries_tags:"en:germany"`. Hits come back under
  `hits`, and `brands` is a list there but a comma-separated string in v2.
- Rate limits per IP: 15 requests/min for product reads, 10 requests/min for
  searches (the Search-a-licious docs state none). Search-as-you-type is
  discouraged. The client does not throttle itself; callers must not loop.
- Every client must send a custom User-Agent of the form
  `AppName/Version (ContactEmail)`.
"""

from __future__ import annotations

import httpx

from snacky.model import FoodCandidate, Nutrients, Serving, Source

KJ_PER_KCAL = 4.184
TIMEOUT_S = 10.0

_FIELDS = ",".join(
    [
        "code",
        "product_name",
        "product_name_de",
        "brands",
        "nutriments",
        "serving_size",
        "serving_quantity",
        "serving_quantity_unit",
    ]
)

# Nutriment keys that map onto Nutrients; the rest of the *_100g keys go to extra.
_MAPPED = {
    "energy-kcal_100g",
    "energy_100g",
    "energy-kj_100g",
    "proteins_100g",
    "fat_100g",
    "carbohydrates_100g",
    "fiber_100g",
}


class OffUnavailable(Exception):
    """Open Food Facts cannot answer right now. The message is written for the
    chat model to relay."""


def _num(value: object) -> float | None:
    # OFF mixes numbers and numeric strings, and sends "" for missing values.
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except TypeError, ValueError:
        return None


def _candidate(product: dict, barcode: str | None = None) -> FoodCandidate | None:
    nutriments = product.get("nutriments") or {}
    kcal = _num(nutriments.get("energy-kcal_100g"))
    if kcal is None:
        kj = _num(nutriments.get("energy_100g"))
        if kj is None:
            kj = _num(nutriments.get("energy-kj_100g"))
        if kj is not None:
            kcal = kj / KJ_PER_KCAL
    protein = _num(nutriments.get("proteins_100g"))
    if kcal is None or protein is None:
        return None

    name = (product.get("product_name_de") or "").strip() or (product.get("product_name") or "").strip()
    ref = barcode or product.get("code")
    if not name or not ref:
        return None

    brands = product.get("brands") or ""
    first = brands[0] if isinstance(brands, list) and brands else brands
    brand = (first.split(",")[0].strip() if isinstance(first, str) else "") or None

    servings: tuple[Serving, ...] = ()
    grams = _num(product.get("serving_quantity"))
    label = (product.get("serving_size") or "").strip()
    unit = product.get("serving_quantity_unit")
    if grams and grams > 0 and label and unit in (None, "", "g"):
        servings = (Serving(label=label, grams=grams),)

    extra = {}
    for key, raw in nutriments.items():
        if key.endswith("_100g") and key not in _MAPPED:
            value = _num(raw)
            if value is not None:
                extra[key] = value

    return FoodCandidate(
        name=name,
        source=Source.OFF,
        per_100g=Nutrients(
            kcal=kcal,
            protein_g=protein,
            fat_g=_num(nutriments.get("fat_100g")) or 0.0,
            carbs_g=_num(nutriments.get("carbohydrates_100g")) or 0.0,
            fibre_g=_num(nutriments.get("fiber_100g")),
        ),
        source_ref=str(ref),
        brand=brand,
        servings=servings,
        extra=extra,
    )


class OffClient:
    def __init__(
        self,
        user_agent: str,
        base_url: str = "https://world.openfoodfacts.org",
        http: httpx.AsyncClient | None = None,
        search_url: str = "https://search.openfoodfacts.org",
    ) -> None:
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=TIMEOUT_S)
        self._base = base_url.rstrip("/")
        self._search_base = search_url.rstrip("/")
        self._headers = {"User-Agent": user_agent}

    async def _get(self, url: str, params: dict[str, str | int]) -> httpx.Response:
        try:
            response = await self._http.get(url, params=params, headers=self._headers, timeout=TIMEOUT_S)
        except httpx.TimeoutException as exc:
            raise OffUnavailable("Open Food Facts did not answer in time, try again in a minute") from exc
        except httpx.TransportError as exc:
            raise OffUnavailable("Open Food Facts cannot be reached, try again in a minute") from exc
        if response.status_code == 429:
            raise OffUnavailable("Open Food Facts is rate-limiting, try again in a minute")
        if response.status_code >= 500:
            raise OffUnavailable("Open Food Facts is having problems, try again in a minute")
        return response

    async def by_barcode(self, barcode: str) -> FoodCandidate | None:
        """None when the product is unknown or has no per-100 g energy and protein."""
        response = await self._get(f"{self._base}/api/v2/product/{barcode}.json", {"fields": _FIELDS})
        if response.status_code == 404:
            return None
        response.raise_for_status()
        body = response.json()
        product = body.get("product")
        if body.get("status") != 1 or not isinstance(product, dict):
            return None
        return _candidate(product, barcode)

    async def search(self, query: str, limit: int = 10) -> list[FoodCandidate]:
        """Products sold in Germany first, German names where they exist."""
        # Products sold in Germany but tagged elsewhere only turn up without the
        # filter, so it is a second query and only when the first finds nothing.
        found = await self._search(f'{query} countries_tags:"en:germany"', limit)
        return found or await self._search(query, limit)

    async def _search(self, q: str, limit: int) -> list[FoodCandidate]:
        params: dict[str, str | int] = {
            "q": q,
            "langs": "de",
            # Ask for extra rows because products without kcal or protein are dropped.
            "page_size": min(max(limit * 3, limit), 50),
            "fields": _FIELDS,
        }
        response = await self._get(f"{self._search_base}/search", params)
        response.raise_for_status()
        found: list[FoodCandidate] = []
        for product in response.json().get("hits") or []:
            candidate = _candidate(product)
            if candidate is not None:
                found.append(candidate)
                if len(found) >= limit:
                    break
        return found

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()
