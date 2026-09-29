"""openGym, read-only: finished workouts and body weight.

Research (openGym 1.3.8, tag v1.3.8, commit f91cde15a1c7):

- ``api/openapi.yaml`` and ``api/server.js``: the server stores each user's data
  as one JSON state document. ``GET /api/data`` returns ``{"state": {...}|null,
  "rev": n}``. ``GET /api/data/rev`` returns only the revision. There is no
  narrower endpoint for workouts or weights, so this client fetches the whole
  document and filters it. It is a personal-sized document, one request per call.
- Finished workouts are ``state.workouts[]``. The server strips the running
  session (``active``) before saving, so every stored entry is finished.
  Fields used: ``start`` and ``end`` (ms since epoch), ``name``, and ``d`` (an
  ISO day written by the device) as a fallback when ``start`` is missing.
- Body weight is ``state.bodyweight[]`` with ``{"d": "YYYY-MM-DD", "w": number,
  "t": ms}``. ``w`` is in ``state.unit`` (``"kg"`` or ``"lb"``, default kg) for
  all entries at once; the app converts the whole log when the unit changes.
  Sources: ``frontend/src/lib/finish-workout.js``, ``frontend/src/sheets.jsx``
  (BwSheet), ``frontend/src/lib/units.js``.

Token. openGym has no API keys. The paired mobile app gets a Bearer token from
the device pairing flow, and this client does the same:

1. The account owner signs in to openGym in the browser and opens Settings,
   "Pair the mobile app". That calls ``POST /api/pair/create`` and shows an
   8-character code that lives 5 minutes and works once.
2. The device redeems it: ``POST /api/pair/redeem`` with ``{"code": "..."}``
   returns ``{"token": "..."}``. Put that in ``OPENGYM_TOKEN``.
3. The token lasts ``SESSION_DAYS`` (default 90). Once it expires, or the owner
   uses "sign out everywhere", the server answers 401 and the owner pairs again.

Never mint a token by signing one with the server's signing secret or by reading
its data directory. The pairing flow is the only supported way to get one, and
it keeps the owner in control of what is issued.
"""

from __future__ import annotations

from datetime import date, datetime

import httpx

from snacky.config import TZ
from snacky.model import BodyWeight, Workout

# From openGym's frontend/src/lib/units.js.
_LB_PER_KG = 2.2046226218


class OpenGymError(Exception):
    """openGym could not be read. The message is fit to show to the user."""


class OpenGymClient:
    def __init__(self, base_url: str, token: str, http: httpx.AsyncClient | None = None) -> None:
        """`token` is a Bearer token from openGym's device pairing flow."""
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._owns_http = http is None
        self._http = http if http is not None else httpx.AsyncClient(timeout=20)

    async def workouts_between(self, start: date, end: date) -> list[Workout]:
        """Finished workouts with start <= day < end."""
        state = await self._state()
        found: list[Workout] = []
        for raw in _dicts(state.get("workouts")):
            if not _is_number(raw.get("end")):  # not finished
                continue
            day = _workout_day(raw)
            if day is None or not start <= day < end:
                continue
            found.append(Workout(day=day, name=_text(raw.get("name")), duration_min=_duration_min(raw)))
        found.sort(key=lambda w: w.day)
        return found

    async def body_weights_between(self, start: date, end: date) -> list[BodyWeight]:
        """Weigh-ins with start <= day < end, in kg."""
        state = await self._state()
        factor = 1 / _LB_PER_KG if state.get("unit") == "lb" else 1.0
        found: list[BodyWeight] = []
        for raw in _dicts(state.get("bodyweight")):
            day = _iso_day(raw.get("d"))
            weight = raw.get("w")
            if day is None or not _is_number(weight) or not start <= day < end:
                continue
            found.append(BodyWeight(day=day, kg=round(weight * factor, 2)))
        found.sort(key=lambda b: b.day)
        return found

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _state(self) -> dict:
        try:
            response = await self._http.get(f"{self._base_url}/api/data", headers=self._headers)
        except httpx.HTTPError as exc:
            raise OpenGymError(f"could not reach openGym: {exc.__class__.__name__}") from exc
        if response.status_code in (401, 403):
            raise OpenGymError("the openGym token was revoked or expired; pair again")
        if response.status_code >= 400:
            raise OpenGymError(f"openGym answered HTTP {response.status_code}")
        try:
            state = response.json().get("state")
        except (ValueError, AttributeError) as exc:
            raise OpenGymError("openGym returned something that is not its state document") from exc
        # `state` is null until the account has synced once.
        return state if isinstance(state, dict) else {}


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _dicts(value: object) -> list[dict]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _iso_day(value: object) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _workout_day(raw: dict) -> date | None:
    """The local day the session started. The device's own `d` is only a
    fallback, since it follows the phone's clock and not SNACKY_TZ."""
    started = raw.get("start")
    if _is_number(started):
        try:
            return datetime.fromtimestamp(started / 1000, TZ).date()
        except OverflowError, OSError, ValueError:
            pass
    return _iso_day(raw.get("d"))


def _duration_min(raw: dict) -> float | None:
    started, ended = raw.get("start"), raw.get("end")
    if _is_number(started) and _is_number(ended) and ended >= started:
        return round((ended - started) / 60000, 1)
    return None
