# Architecture

## One process, two ports

Snacky is one Python process that owns one SQLite file.

- Port 8000 serves MCP over streamable HTTP, stateless, for the chat
  assistant. It is meant to be reachable from the assistant only.
- Port 8080 serves the web UI and its JSON API, meant to sit behind an
  authenticating proxy.

## Modules

| Module | Owns |
|---|---|
| `snacky.model` | the shared types; every other module imports them |
| `snacky.config` | settings from the environment |
| `snacky.store` | the SQLite log: foods, servings, entries, goals, quick items, summaries |
| `snacky.sources.bls` | the BLS 4.0 index, built once at image build, read-only at runtime |
| `snacky.sources.off` | Open Food Facts client |
| `snacky.sources.tandoor` | Tandoor client: recipe nutrition, food properties |
| `snacky.sources.opengym` | openGym client: workouts, body weight |
| `snacky.lookup` | the lookup order below: search, resolve a ref, resolve a barcode |
| `snacky.mcp_server` | the MCP tools and the `/health` route; `create_mcp` builds the server, `create_mcp_app` its stateless HTTP app |
| `snacky.__main__` | wires the clients and serves MCP and the web UI as two uvicorn servers in one loop |
| `snacky.web` | web UI (later) |

## Lookup order

1. Foods already stored, including cached Open Food Facts products.
2. BLS.
3. Open Food Facts, by barcode or search. Every product fetched is stored.
4. A model estimate, stored with `source = ai_estimate` and shown as one.

The assistant names foods and grams. It supplies nutrient numbers only when
reading a label (`source = label`) or when nothing above knows the food.

A search result carries a `ref` (`food:<id>`, `bls:<code>` or `off:<barcode>`).
`log_food` and `add_serving` take a ref and store the food on first use, so it
is found locally from then on. A BLS or Open Food Facts hit that is already
stored is listed once, as the stored food. When Open Food Facts is down, a
search returns the local results and a note.

A barcode is looked up in stored foods (a label reading first, then a cached
product) before Open Food Facts.

## MCP tools

`search_food`, `log_food`, `log_barcode`, `log_label`, `log_recipe_portion`,
`log_estimate`, `day_summary`, `week_summary`, `update_entry`, `delete_entry`,
`set_goal`, `add_serving`. Every logging result names the food's source.

`log_estimate` looks each plate item up by its `search_name` in stored foods
and BLS first and uses the model's numbers only when nothing matches. It never
calls Open Food Facts. The deployment puts this tool behind an approval step.

`eaten_at` is an ISO datetime, `HH:MM` or empty (now). A bare time means the
latest such time that is not in the future, so "23:30" said at 00:20 is the
evening before. A time more than 15 minutes ahead is refused.

## Entries

An entry stores an absolute snapshot of its nutrients. Correcting a food later
does not change past days. The entry also keeps the food id and the grams, so
micronutrients can be computed from the source later.

`origin_ref` is unique. A recipe portion logged from a Tandoor cook log uses
`tandoor-cooklog:<id>`, so the same cook log cannot be logged twice.

## Goals

A goal has a nutrient, a kind (`min`, `max`, `band`) and a `valid_from` date.
A day is judged by the goals that applied on that day.

## Meals

Nobody says which meal an entry belongs to. Entries less than
`SNACKY_MEAL_GAP_MIN` minutes apart (default 90) form one meal.
