---
version: 1
slug: "src-snacky-web"
primary_target: "src/snacky/web"
related_targets: []
---

Scope: the Snacky web UI (day, week, quick items, entry edit). Mode: Operate. A phone glance in the kitchen or after training: how much protein today, how much is missing, what closes the gap; fix a wrong entry; see the week.

## Direction contract

THESIS: The day is a high-protein pack. The front carries one giant claim, the protein eaten, and a sticker with the gap; the back carries the Nährwerttabelle as the entry list. It refuses the tracker dashboard of rings, cards and a neon accent.

OWN-WORLD: Drenched Himbeer (#D6247A) printed card stock, deep raspberry for the unfilled part of the front, Senf (#FFC629) round stickers, print black, a white label panel with the LMIV rule system (one heavy rule, one hairline, nothing else). Bricolage Grotesque ExtraBold for the brand and claims, Fira Sans Compressed Heavy for claim numerals, Fira Sans Condensed for the table.

STORY: The person sees the number, sees the gap on the sticker, taps a coupon that closes it or scrolls the table to fix an entry, and on a met day sees the whole front go solid with the sticker flipped to GESCHAFFT.

FIRST VIEWPORT: On a 390px phone: brand strip at the top, then the pack front filling most of the screen: the claim numerals at 6rem, PROTEIN beneath, the sticker overlapping the top right, the fill rising from the bottom to the share of the goal, kcal as a small secondary claim, the quick coupons at the bottom edge of the front. Main navigation in a bottom bar.

FORM: Nährwerttabelle and high-protein packaging, number 7 of the ordered list, seed key 1ab1eac8. Signature interaction: the pack front fills to the goal share once on load; reaching the goal turns it solid and flips the sticker.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Raises

- From the parametric identity: the day's state colours the whole front, not only a bar.
- From the centre-rail setting: exactly two rule weights, as on the real table.
- From the tensegrity column: the gap sits beside the total as its counterpart.
- From the cracktro scroller: rank by size alone, one step per level.

## Unresolved

- Per-meal protein reference: shown only when SNACKY_MEAL_PROTEIN_MIN is set; the owner has not decided a default.
