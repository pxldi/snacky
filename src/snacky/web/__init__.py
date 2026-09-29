"""The web UI and its JSON API, served on its own port behind an
authenticating proxy."""

from __future__ import annotations

from starlette.applications import Starlette

from snacky.sources.opengym import OpenGymClient
from snacky.store import Store


def create_app(store: Store, *, opengym: OpenGymClient | None = None) -> Starlette:
    """The web app. `opengym` marks training days in the week view when set."""
    raise NotImplementedError
