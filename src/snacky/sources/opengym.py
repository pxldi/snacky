"""openGym, read-only: finished workouts and body weight."""

from __future__ import annotations

from datetime import date

import httpx

from snacky.model import BodyWeight, Workout


class OpenGymClient:
    def __init__(self, base_url: str, token: str, http: httpx.AsyncClient | None = None) -> None:
        """`token` is a Bearer token from openGym's device pairing flow."""
        raise NotImplementedError

    async def workouts_between(self, start: date, end: date) -> list[Workout]:
        """Finished workouts with start <= day < end."""
        raise NotImplementedError

    async def body_weights_between(self, start: date, end: date) -> list[BodyWeight]:
        raise NotImplementedError

    async def aclose(self) -> None:
        raise NotImplementedError
