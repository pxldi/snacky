# Snacky

A protein and calorie log that you never have to open to fill in. You tell a
chat assistant what you ate (a message, a voice note, a recipe portion, a
photo of a label or a plate), and the assistant calls Snacky's MCP tools.
Snacky looks the food up in a nutrient database and keeps the log. A small
web UI shows the day and the week and lets you correct entries.

Status: early. The MCP server runs; the web UI is not built yet.

## How it works

- The assistant names foods and grams. The numbers come from a database: the
  German Bundeslebensmittelschlüssel, Open Food Facts, or the recipe's own
  nutrition in Tandoor. A number the model estimated is stored and shown as
  an estimate.
- Each log entry keeps a copy of its nutrients, so correcting a food later
  does not change past days.
- One process owns one SQLite file. It serves MCP on one port and the web UI
  on another.

`docs/ARCHITECTURE.md` has the data model and the interfaces.

## Running

    docker run --read-only -v snacky-data:/data -p 8000:8000 ghcr.io/pxldi/snacky:<tag>

The image contains the BLS index at `/app/data/bls.sqlite`, converted from the
pinned BLS download at build time. Without that file the server starts and
skips BLS, with a warning. `/data` is the only path written at runtime.

| Port | Serves |
|---|---|
| 8000 | MCP over streamable HTTP at `/mcp`, stateless, and `/health` (reports the build). Meant for the assistant only. |
| 8080 | The web UI. Not built yet; until then only 8000 is served. |

| Variable | Default | Meaning |
|---|---|---|
| `SNACKY_DB` | `/data/snacky.sqlite` | the log |
| `SNACKY_BLS` | `/app/data/bls.sqlite` | the BLS index |
| `SNACKY_TZ` | `Europe/Berlin` | day boundaries and meal grouping |
| `SNACKY_MEAL_GAP_MIN` | `90` | minutes between entries that start a new meal |
| `SNACKY_OFF_USER_AGENT` | `snacky/0.1 (+https://github.com/pxldi/snacky)` | sent to Open Food Facts |
| `SNACKY_MCP_PORT`, `SNACKY_WEB_PORT` | `8000`, `8080` | listen ports |
| `TANDOOR_URL`, `TANDOOR_TOKEN` | unset | enables `log_recipe_portion` |
| `OPENGYM_URL`, `OPENGYM_TOKEN` | unset | adds training days and body weight to `week_summary` |
| `IMAGE_SHA` | set by the image | the `build` value in `/health` |

## Data sources

- **Bundeslebensmittelschlüssel (BLS), Version 4.0.** Max Rubner-Institut
  (2025), licensed under CC BY 4.0. https://www.blsdb.de/
- **Open Food Facts**, licensed under the Open Database License.
  https://world.openfoodfacts.org/

## License

GPL-3.0. See `LICENSE`.
