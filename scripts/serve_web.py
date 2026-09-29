"""Serve only the web app on http://127.0.0.1:8080 for looking at it locally.

    uv run python scripts/serve_web.py /tmp/snacky-demo.sqlite [--fake-training]

--fake-training marks every other day as a training day, so the week view can
be seen without an openGym server.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

import uvicorn

from snacky.model import Workout
from snacky.store import Store
from snacky.web import create_app


class _FakeTraining:
    async def workouts_between(self, start: date, end: date) -> list[Workout]:
        days = [start + timedelta(days=i) for i in range((end - start).days)]
        return [Workout(day=d, name="Oberkörper", duration_min=55) for d in days if d.toordinal() % 2 == 0]


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        raise SystemExit("usage: serve_web.py DB [--fake-training]")
    opengym = _FakeTraining() if "--fake-training" in sys.argv else None
    app = create_app(Store(args[0]), opengym=opengym)  # type: ignore[arg-type]
    uvicorn.run(app, host="127.0.0.1", port=8080)


if __name__ == "__main__":
    main()
