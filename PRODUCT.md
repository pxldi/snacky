# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

One person at a time, self-hosting their own instance: someone who eats
plant-based and trains for muscle, and wants to hit a daily protein target
spread over several meals. They log food by talking to a chat assistant
(Clanky, a Telegram bot) with a message, a voice note, a recipe portion, or a
photo of a label or a plate. They open the web UI on a phone, in the kitchen
or after a gym session, to glance at the day, to see the week, to fix a wrong
entry, or to tap something they eat often.

## Product Purpose

Snacky keeps the food log so nobody has to type meals into an app. The chat
assistant names foods and amounts; Snacky finds the numbers in a nutrient
database and keeps the entries. Success is a day where protein reaches the
goal, spread over meals, without the person ever filling in a form.

## Positioning

The log is filled by conversation, not by forms. Every number comes from a
database (the German Bundeslebensmittelschlüssel, Open Food Facts, or the
recipe's own nutrition in Tandoor), and anything a model estimated is marked
as an estimate. The web UI is the mirror of that conversation, not the input.

## Operating Context

- Input: a Telegram assistant with MCP tools; an evening check asks about
  cooked meals and portions; a Sunday message reviews the week.
- The web UI runs on the owner's home server behind a login, reached from a
  phone on the home network or VPN.
- Protein per meal matters as well as the daily total (a few meals of a
  solid portion each).
- Training sessions come from a separate gym tracker (openGym) and can be
  shown next to the days.

## Capabilities and Constraints

- Server-rendered HTML (Starlette, Jinja2), forms work without JavaScript.
- Strict Content-Security-Policy: no inline scripts or styles, no CDNs, no
  external fonts; fonts and assets must ship in `src/snacky/web/static/`.
- UI copy is German. Code and comments are English.
- The repository is public: no personal data, goals, meals or body data in
  code, fixtures, demo data or screenshots committed to the repo.
- Goals (daily protein minimum, kcal band) live in the database and can
  change over time; a day is judged by the goal that applied on that day.
- Entries carry their source (BLS, Open Food Facts, label, Tandoor, manual,
  estimate) and, for estimates, a confidence.

## Brand Commitments

- The name is Snacky, the sibling of the chat assistant Clanky. The tone is
  playful and encouraging: showing up counts more than performance, and a
  short day is never scolded.
- Everything shown as a suggestion or example is plant-based.
- Data sources are credited: "Bundeslebensmittelschlüssel 4.0, Max
  Rubner-Institut, CC BY 4.0" and "Open Food Facts, ODbL".

## Evidence on Hand

- Demo data: `scripts/demo_db.py` writes two weeks of made-up plant-based
  entries, goals and quick items. It is synthetic and labelled as such.
- No logo, illustration or photography exists yet.

## Product Principles

1. The gap to the protein goal is the most useful fact on the screen.
2. Reaching the goal is a moment worth marking; missing it is information,
   not failure.
3. Numbers are only as good as their source, so the source is always visible.
4. The UI never becomes the place where food has to be typed in.

## Accessibility & Inclusion

Used one-handed on a phone: touch targets of at least 44 px, readable in
both light and dark, meaning never carried by colour alone, and every state
announced to screen readers.
