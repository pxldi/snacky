# Snacky

A protein and calorie log that you never have to open to fill in. You tell a
chat assistant what you ate (a message, a voice note, a recipe portion, a
photo of a label or a plate), and the assistant calls Snacky's MCP tools.
Snacky looks the food up in a nutrient database and keeps the log. A small
web UI shows the day and the week and lets you correct entries.

Status: early. Nothing here runs yet.

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

## Data sources

- **Bundeslebensmittelschlüssel (BLS), Version 4.0.** Max Rubner-Institut
  (2025), licensed under CC BY 4.0. https://www.blsdb.de/
- **Open Food Facts**, licensed under the Open Database License.
  https://world.openfoodfacts.org/

## License

GPL-3.0. See `LICENSE`.
