"""The web UI and its JSON API, served on its own port behind an
authenticating proxy."""

from snacky.web.app import create_app

__all__ = ["create_app"]
