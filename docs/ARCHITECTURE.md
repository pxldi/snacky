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
| `snacky.lookup` | the lookup order below (later) |
| `snacky.mcp_server` | MCP tools (later) |
| `snacky.web` | web UI (later) |

## Lookup order

1. Foods already stored, including cached Open Food Facts products.
2. BLS.
3. Open Food Facts, by barcode or search. Every product fetched is stored.
4. A model estimate, stored with `source = ai_estimate` and shown as one.

The assistant names foods and grams. It supplies nutrient numbers only when
reading a label (`source = label`) or when nothing above knows the food.

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
