"""The demo database builder works and every page renders on its data."""

import importlib.util
from datetime import date, timedelta
from pathlib import Path

from starlette.testclient import TestClient

from snacky.web import create_app

SCRIPT = Path(__file__).parent.parent / "scripts" / "demo_db.py"


def test_demo_database_renders(tmp_path):
    spec = importlib.util.spec_from_file_location("demo_db", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    store = module.build(tmp_path / "demo.sqlite", today=date(2026, 9, 29))
    try:
        assert len(store.quick_items()) == 3
        assert (
            sum(
                store.day_summary(date(2026, 9, 29) - timedelta(days=d)).totals.protein_g for d in range(1, 8)
            )
            > 0
        )
        client = TestClient(create_app(store))
        for path in ["/", "/week", "/week?start=2026-09-14", "/quick", "/api/week", "/?day=2026-09-20"]:
            assert client.get(path).status_code == 200, path
    finally:
        store.close()
