"""Settings read from the environment. Nothing personal has a default here:
goals live in the database, addresses and tokens come from the deployment."""

import os
from datetime import timedelta
from zoneinfo import ZoneInfo

# Day boundaries and meal grouping use local time.
TZ = ZoneInfo(os.environ.get("SNACKY_TZ", "Europe/Berlin"))

# Entries closer together than this belong to the same meal.
MEAL_GAP = timedelta(minutes=int(os.environ.get("SNACKY_MEAL_GAP_MIN", "90")))

DB_PATH = os.environ.get("SNACKY_DB", "/data/snacky.sqlite")
BLS_PATH = os.environ.get("SNACKY_BLS", "/app/data/bls.sqlite")

# Open Food Facts asks every client to identify itself.
OFF_USER_AGENT = os.environ.get("SNACKY_OFF_USER_AGENT", "snacky/0.1 (+https://github.com/pxldi/snacky)")

TANDOOR_URL = os.environ.get("TANDOOR_URL", "")
TANDOOR_TOKEN = os.environ.get("TANDOOR_TOKEN", "")
OPENGYM_URL = os.environ.get("OPENGYM_URL", "")
OPENGYM_TOKEN = os.environ.get("OPENGYM_TOKEN", "")
