---
name: Snacky
description: A protein log shown as a high-protein pack, with the day's claim on the front and the Nährwerttabelle on the back.
colors:
  himbeer: "#d6247a"
  himbeer-press: "#b81d69"
  senf: "#ffc629"
  print: "#141014"
  print-lift: "#3a2a36"
  paper: "#ffffff"
  paper-blush: "#ffe9f3"
  ground: "#d6247a"
  unfilled: "#7e1247"
  fill: "#d6247a"
  panel: "#ffffff"
  ink: "#141014"
  ink-soft: "#5c525a"
  field: "#ffffff"
  track: "#4a0e2c"
  edge: "#141014"
  nav-rule: "#141014"
  danger: "#7e1247"
  focus: "#141014"
  ground-dark: "#2b0819"
  unfilled-dark: "#4a0e2c"
  panel-dark: "#1b0b13"
  ink-dark: "#fff0f6"
  ink-soft-dark: "#cfa9bc"
  field-dark: "#2b0819"
  danger-dark: "#ff8fbf"
  edge-dark: "#d6247a"
  nav-rule-dark: "#d6247a"
typography:
  display:
    fontFamily: "\"Snacky Claim\", \"Arial Narrow\", sans-serif"
    fontSize: "6rem"
    fontWeight: 900
    lineHeight: 0.9
    letterSpacing: "0"
    fontFeature: "\"tnum\", \"lnum\""
  headline:
    fontFamily: "\"Snacky Display\", \"Arial Black\", sans-serif"
    fontSize: "2.75rem"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "0.01em"
  brand:
    fontFamily: "\"Snacky Display\", \"Arial Black\", sans-serif"
    fontSize: "1.75rem"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "-0.01em"
  sticker-number:
    fontFamily: "\"Snacky Claim\", \"Arial Narrow\", sans-serif"
    fontSize: "3.25rem"
    fontWeight: 900
    lineHeight: 0.95
    letterSpacing: "-0.02em"
  page-title:
    fontFamily: "\"Snacky Text\", \"Arial Narrow\", sans-serif"
    fontSize: "2.25rem"
    fontWeight: 700
    lineHeight: 1.05
  title:
    fontFamily: "\"Snacky Text\", \"Arial Narrow\", sans-serif"
    fontSize: "1.75rem"
    fontWeight: 700
    lineHeight: 1.1
  body:
    fontFamily: "\"Snacky Text\", \"Arial Narrow\", sans-serif"
    fontSize: "1.125rem"
    fontWeight: 700
    lineHeight: 1.4
    fontFeature: "\"tnum\", \"lnum\""
  table-row:
    fontFamily: "\"Snacky Text\", \"Arial Narrow\", sans-serif"
    fontSize: "1.25rem"
    fontWeight: 400
    lineHeight: 1.2
  meta:
    fontFamily: "\"Snacky Text\", \"Arial Narrow\", sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.3
  label:
    fontFamily: "\"Snacky Text\", \"Arial Narrow\", sans-serif"
    fontSize: "0.875rem"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "0.1em"
rounded:
  none: "0"
  control: "0.25rem"
spacing:
  xs: "0.25rem"
  sm: "0.5rem"
  md: "0.75rem"
  base: "1rem"
  lg: "1.25rem"
  xl: "1.5rem"
  xxl: "2rem"
  front-top: "3.5rem"
components:
  button-ground:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.print}"
    rounded: "{rounded.control}"
    typography: "{typography.body}"
    padding: "0 1.125rem"
    height: "3rem"
  button-ground-hover:
    backgroundColor: "{colors.paper-blush}"
  button-primary:
    backgroundColor: "{colors.himbeer}"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
    typography: "{typography.body}"
    padding: "0 1.125rem"
    height: "3rem"
  button-primary-hover:
    backgroundColor: "{colors.himbeer-press}"
  button-ink:
    backgroundColor: "{colors.print}"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
    typography: "{typography.body}"
    padding: "0 1.125rem"
    height: "3rem"
  button-ink-hover:
    backgroundColor: "{colors.print-lift}"
  button-danger:
    textColor: "{colors.danger}"
    rounded: "{rounded.control}"
    padding: "0 1.125rem"
    height: "3rem"
  input:
    backgroundColor: "{colors.field}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 0.75rem"
    height: "3rem"
  nav-bottom:
    backgroundColor: "{colors.print}"
    textColor: "{colors.paper}"
    height: "56px"
  nav-bottom-active:
    textColor: "{colors.senf}"
  pack-front:
    backgroundColor: "{colors.unfilled}"
    textColor: "{colors.paper}"
    rounded: "{rounded.none}"
    padding: "3.5rem 1rem 1.25rem"
  pack-front-met:
    backgroundColor: "{colors.fill}"
  sticker:
    backgroundColor: "{colors.senf}"
    textColor: "{colors.print}"
    typography: "{typography.sticker-number}"
    size: "8.5rem"
  coupon:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.print}"
    rounded: "{rounded.none}"
    height: "3.75rem"
  flash-tag:
    backgroundColor: "{colors.senf}"
    textColor: "{colors.print}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "0.05rem 0.45rem"
  flash-tag-ink:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.panel}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "0.05rem 0.45rem"
  label-panel:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "1.25rem 1rem 1.5rem"
  undo-band:
    backgroundColor: "{colors.senf}"
    textColor: "{colors.print}"
    padding: "0.5rem 1rem"
---

# Design System: Snacky

## Overview

**Creative North Star: "The Protein Pack"**

Every screen is a piece of printed packaging. The page ground is raspberry card stock. The day sits on a pack front whose deep raspberry field fills from the bottom to the share of the protein goal, with one huge number as the claim and a mustard seal sticker carrying the gap. Behind it, a white label panel holds the entries as a German nutrition table, ruled the way a real Nährwerttabelle is ruled.

Density is low on the front and moderate on the label. The front shows one large number, and the table lists the detail in plain condensed type. The day's state is shown in colour: the front's fill rises with the protein eaten, and a met day turns the whole front solid and swaps the sticker to a check and "Geschafft!". Motion happens once, on load, and only for that fill and that sticker.

Surfaces read as objects laid on the card: the front, the sticker and the coupons cast soft shadows, and everything else is flat print. Tilts are small and deliberate (the wordmark, the sticker, the coupon flag). The dark scheme keeps the same pack and dims the card to a near-black raspberry; stickers, coupons, buttons and the nav keep their light-scheme inks.

**Key Characteristics:**
- Drenched raspberry ground, no neutral page background.
- One claim numeral per front, set in a compressed heavy face at 6rem.
- A seal sticker in Senf that states the gap, flips on a met day.
- Label panels ruled with one heavy rule and hairlines, like a food label.
- Quick items as tear-off coupons with a perforated protein stub.
- A print-black bottom bar on phones that moves into the brand strip on wide screens.

## Colors

A two-ink raspberry print with one mustard spot colour and print black.

### Primary
- **Himbeer** (`himbeer`): the pack. It is the page ground, the fill of the front, the primary button, the week bars and the caret. In the light scheme `ground`, `fill` and `himbeer` share one value; the three roles exist because `ground` darkens in the dark scheme while `fill` stays Himbeer.
- **Deep Raspberry** (`unfilled`): the part of the front not yet filled and the cap strip above the fill. It also serves as `danger` in the light scheme, so the delete button reads as the pack's own dark ink.

### Secondary
- **Senf** (`senf`): the sticker seal, the "schließt die Lücke" flag on a coupon, the "Heute" tag in the week, the undo band, the active nav mark and text selection. Senf always appears as a printed patch with print-black text, or as a mark on print black.

### Neutral
- **Print Black** (`print`): the bottom nav (with a 2px `nav-rule` on top: print black in light, Himbeer in dark, so the bar reads against the night ground), the ink button (its border is `edge`: print black in light, Himbeer in dark), text on Senf and on coupons, and the table ink in the light scheme (`ink`, `focus`).
- **Label White** (`paper`, `panel`, `field`): coupons, ground buttons, the label panel and inputs. In the dark scheme `paper` stays white while `panel` becomes `panel-dark` and `field` becomes `field-dark`; the label panel is white in the light scheme only.
- **Night Track** (`track`): the empty track of the week bars, one value in both schemes. It sits 3.1:1 below the Himbeer bar so the bar reads in light and dark.
- **Muted Plum** (`ink-soft`): future days in the week list. Nothing else.
- **Night Card** (`ground-dark`, `unfilled-dark`, `panel-dark`, `ink-dark`, `ink-soft-dark`, `danger-dark`): the dark scheme's ground, unfilled front, panel, table ink and soft text, and a pink danger that stays legible on the dark panel.
- **Press tones** (`himbeer-press`, `paper-blush`, `print-lift`): custom properties on `:root`, used for the hover states of the primary, ground and ink buttons.

### Named Rules
**The Drenched Ground Rule.** The page ground is always the pack colour, `ground`. There is no grey or white page behind the pack; white appears only as a printed object on it (label panel, coupon, button).

**The State Colours the Front Rule.** The day's protein state is shown by how much of the front is filled with Himbeer, from the bottom up. A met day fills the whole front, cap strip included. Numbers and words carry the same state, so colour is never the only signal.

**The Spot Colour Rule.** Senf is a patch or a mark, never text on raspberry. Text on Senf is print black.

## Typography

**Display Font:** Bricolage Grotesque ExtraBold, self-hosted as "Snacky Display" (with Arial Black)
**Claim Font:** Fira Sans Compressed Heavy, self-hosted as "Snacky Claim" (with Arial Narrow)
**Body Font:** Fira Sans Condensed Regular and Bold, self-hosted as "Snacky Text" (with Arial Narrow)

**Character:** A packaging stack. The compressed heavy face sets the claims' numerals, the grotesque shouts the words on the pack, and the condensed sans runs the table and the controls. Numerals are tabular and lining everywhere so columns line up.

### Hierarchy
- **Display** (`display`): the claim numeral on the front. One per front.
- **Headline** (`headline`): the uppercase claim word under the numeral ("Protein", "Tagen dabei"). 2.25rem on the week front.
- **Brand** (`brand`): the wordmark in the strip, tilted -2deg.
- **Sticker number** (`sticker-number`): the gap on the seal; the sticker's words use the display face at 1.125rem uppercase.
- **Page title** (`page-title`): the entry name on edit and delete pages, and the quick page title.
- **Title** (`title`): panel headings ("Nährwerte", "Tage der Woche") and the table total.
- **Body** (`body`): text on the raspberry ground and on controls, always bold.
- **Table row** (`table-row`): entry names and row numbers inside the label panel.
- **Meta** (`meta`): amount and source under an entry, fine print.
- **Label** (`label`): short uppercase data tags ("Heute", "Training") and the cap strip ("Ziel 120 g", or "So 27.9. · Ziel 120 g" on a past day). Table field names on the edit page use the same case at the same size, 0.06em, regular weight.

### Named Rules
**The Ramp Rule.** The stylesheet uses nine sizes and no others, as custom properties on `:root`: 0.875, 1, 1.125, 1.25, 1.75, 2.25, 2.75, 3.25 and 6rem (`--t-xs` to `--t-claim`). New text picks the nearest step.

**The Two Voices Rule.** Text on the raspberry ground is bold (700). The label panel resets to regular (400), and inside it bold marks only headings, protein numbers and the total.

**The Numerals-Only Claim Rule.** Snacky Claim sets numbers only: the front claim, the sticker gap and the coupon stub. Words on the pack use Snacky Display.

**The Label Carries Data Rule.** Uppercase letter-spaced type is used only for tags and field names that carry a value or a status. It never sits as a decorative line above a heading.

## Layout

Phone first, one column. The brand strip runs across the top with the date on the right, the pack front spans the full width below it, and the label panel follows with 0.75rem side margins. A print-black nav bar (56px plus the safe-area inset) is fixed to the bottom, and the body reserves that height plus 1.5rem.

From 60rem the layout splits into two columns inside a 68.75rem container: the pack column (24rem to 30rem) sticks 1rem from the top, and the label panel takes the rest with a 2rem gap. The nav leaves the bottom and sits in the brand strip as a row of links. Edit, delete and form pages use a single 40rem column.

Spacing steps are 0.25, 0.5, 0.75, 1, 1.25, 1.5 and 2rem. Horizontal page padding is 1rem. The front has a 3.5rem top pad to clear its 2.5rem cap strip. Touch targets are at least 2.75rem (44px); buttons and inputs are 3rem tall. Paired buttons (day navigation, form actions) sit in a two-column grid or wrap at 9rem.

## Elevation & Depth

Flat print with three physical exceptions. Objects that would be separate pieces of card on a real pack (the front, the sticker and the coupons) cast a soft shadow onto the ground. The label panel, buttons, tags and the nav are flat.

### Shadow Vocabulary
- **Front lift** (`box-shadow: 0 10px 22px -6px rgb(20 16 20 / 0.5)`): lifts the pack front off a ground of the same colour as its fill.
- **Sticker** (`filter: drop-shadow(0 3px 4px rgb(20 16 20 / 0.4))`): follows the seal's scalloped outline.
- **Coupon** (`filter: drop-shadow(0 2px 2px rgb(20 16 20 / 0.35))`): follows the notched coupon outline.

### Named Rules
**The Printed Object Rule.** A shadow means "a separate piece stuck on the pack". Panels and controls stay flat, and every shadow is soft and blurred, never hard-edged.

## Shapes

Square print. Panels, the front, coupons and tags have no radius. Only controls (buttons and inputs) are rounded, at 0.25rem, with 2px solid borders in the current ink.

Recurring forms:
- **The seal:** a 16-point scalloped starburst in Senf, 8.5rem square, rotated -8deg, overlapping the front's top right corner.
- **The coupon:** a white slip with two semicircular notches (0.5rem radius) cut top and bottom where the stub tears off, and a 2px dashed perforation (5px dash, 4px gap) between body and stub.
- **The cap strip:** a 2.5rem band across the top of a day front, closed by a 2px dashed white rule.
- **Table rules:** a 6px heavy rule (`--heavy`) opens each table and closes the total; 1px hairlines (`--hair`) separate meals and rows.

**The Two Rules Rule.** Inside a label table there are exactly two rule weights, 6px and 1px, in the current ink. Dashed lines, 2px borders and the nav mark belong to the pack and controls, never to the table. The dashed underline on an estimated number is text decoration, not a rule.

## Components

### Buttons
Printed and solid, sized for a thumb.
- **Shape:** gently squared corners (`rounded.control`), 2px solid border, 3rem tall, bold body type, optional 24px icon with 0.5rem gap.
- **Ground:** white slip with print-black border and text; the default on the raspberry ground (day and week navigation).
- **Primary:** Himbeer fill, white text; the one recommended action on a page ("Speichern", "Zur Schnellwahl", and "Abbrechen" on the delete page, where cancelling is the recommended action).
- **Ink:** print-black fill, white text; used on Senf (undo) and for the confirm step of removing a quick item.
- **Danger:** transparent with `danger` border and text.
- **Plain:** transparent with the current ink; secondary actions in panels ("Suchen", "Zurück zum Tag").
- **Hover:** ground, primary and ink step to their press tones; plain and danger take a 10% ink tint. Disabled is 0.55 opacity with a progress cursor, set after a form submits.
- **Focus:** 3px outline in `focus` at 2px offset, plus a 2px Senf ring.

### Coupons
Tear-off quick items. A white slip with the food name (1.25rem bold) and grams (meta) on the left, and the protein as "+23,4 g" in Snacky Claim at 1.75rem on a 5.5rem stub on the right, split by the dashed perforation and the notches. They wrap in a flexible row with a 15rem basis on the front and stack at up to 28rem on the quick page. A press moves the coupon down 1px. Focus draws the outline around the whole slip. On the front and on the quick page the coupons are the same slip; the accessible name reads food, grams, protein and "eintragen". The coupon that closes today's gap carries a Senf flag ("schließt die Lücke") tilted -2deg across its top left edge.

### Label panel
The back of the pack. Panel background, ink text, square, 1.25rem 1rem 1.5rem padding (1.5rem 1.5rem 2rem from 60rem). A title-size heading and a date subline sit above the heavy rule. Meals are headed by the clock time and their protein; entries are full-width links with the name and meta on the left, protein (bold) with kcal (small) on the right and a chevron that marks the row as editable. The date is not repeated here; the brand strip carries it. Estimates say "geschätzt, unsicher" or "geschätzt, eher sicher". Estimated protein carries a "≈" and a 2px dashed underline. The total block closes with a second heavy rule: "Summe" and protein at title size, the gap in words and kcal below. The edit page uses the same panel for a two-column nutrient table (per 100 g and per portion) with Eiweiß in bold at 1.5rem, followed by field-name rows.

### Inputs / Fields
- **Style:** 3rem tall, 2px solid ink border, `rounded.control`, `field` background, 1.25rem regular text, Himbeer caret and accent colour.
- **Label:** bold label above the field with a 0.35rem gap.
- **Focus:** the shared 3px outline and Senf ring.
- **Error:** a print-black block with white bold text above the form.

### Navigation
- **Phone:** a print-black bar fixed to the bottom with three equal cells (Heute, Woche, Schnell), each a 24px icon above a 0.875rem label in white, under a 2px `nav-rule`. The current page turns Senf and gets a 4px Senf bar across the top of its cell, inset 20% from each side.
- **Wide:** the same links sit in the brand strip on the ground, icon beside label at 1.0625rem; the current page stays white with the Senf bar underneath.
- **Icons:** line icons on a 24px grid with a 2.5 stroke and round caps and joins, drawn in `currentColor`.

### Pack front
The signature. A column on `unfilled` with the Himbeer fill drawn as an SVG rectangle rising from the bottom to the goal share. The day front shows the cap strip ("Ziel" and the goal; on any day but today the weekday and date come first, and the whole cap turns Senf with print-black text and a print-black dashed rule, so a past day cannot pass for today), the claim numeral with a "g" unit at 2rem, the claim word, a fine line for the estimated share, a training tag when openGym reports a workout for the day, a kcal line and the coupons. The week front drops the cap and states "1 von 6 / Tagen dabei" (days logged of days finished, with "von" in the display face at 2.25rem) and, beneath it, "Ø 101 von 120 g Protein". Its fill is the protein of the finished days over their goals, and today counts only once it is met, so an unfinished day never reads as a miss. It goes solid when that share reaches 1.

### Sticker
The gap, stated on a seal. States: open ("Noch" over the gap in grams), met (check icon at 2.25rem with a 3.5 stroke, "Geschafft!", and the surplus when it is at least 0.5 g), missed (the gap over "Unter Ziel"), and today with nothing logged ("Los geht's" at 1.5rem). No sticker when no goal is set or on a past day with no entries.

### Flash tags
Small square tags in `label` type. Senf with print black marks today in the week. `ink` on `panel` marks training days in the week and a meal that reached the per-meal reference ("ab 30 g"); on the day front the training tag is print black with white text.

### Week rows
Each day is a full-width link: the date (bold 1.25rem) and status on the first line, then a row with a 0.875rem SVG bar (Himbeer on the `track`, a white 3px tick at the goal) and, in a fixed 7.5rem column, the protein as "101 von 120 g" with kcal beneath, so every bar shares one axis. Met days add a check icon and "geschafft"; a short day is stated in numbers and never labelled. Each row link has one accessible name ("Mo, 28.9., 154 von 120 g, geschafft, Training") and the bar is decorative. Future days show "–" in `ink-soft` and no bar. The list closes with a heavy rule.

### Undo band
A full-width Senf band after a quick log: the logged item in body type and an ink "Rückgängig" button. On phones it is fixed just above the bottom nav, within thumb reach and clear of the claim; from 60rem it returns to the top of the page. The page title also reads "Eingetragen: {name}" while it shows. It is a live status region.

### Motion
On load, the fill scales up from the bottom (from 0, or from the share it had before the entry that the undo band names, so a log reads 97 to 107) over 0.7s with `cubic-bezier(0.16, 1, 0.3, 1)`. On a met day the front turns solid when the rise ends, and the sticker lands at 0.65s over 0.55s (from -18deg and 130% to -6deg and 96%, settling at -8deg). All of it runs only under `prefers-reduced-motion: no-preference`; otherwise the final state shows at once.

## Do's and Don'ts

### Do:
- **Do** keep the page ground on `ground` and put white only on printed objects (panel, coupon, ground button).
- **Do** show the day's state as the Himbeer fill share of the front, and repeat it in the sticker's words and the table's total.
- **Do** set every claim numeral in Snacky Claim 900 with tabular lining figures, one claim per front.
- **Do** open every label table with the 6px rule and separate rows with 1px hairlines.
- **Do** put print-black text on Senf and keep Senf to seals, flags, tags, the undo band and the nav mark.
- **Do** keep touch targets at 2.75rem or more and draw focus with the 3px outline plus the Senf ring.
- **Do** gate every animation behind `prefers-reduced-motion: no-preference` and keep motion to the fill rise and the sticker landing.

### Don't:
- **Don't** add a third rule weight, a dashed line or a coloured rule inside a label table.
- **Don't** set Senf text on raspberry or use Senf for body copy.
- **Don't** put shadows on the label panel, buttons or tags, and don't use hard offset shadows anywhere.
- **Don't** round the front, the panel, coupons or tags; the 0.25rem radius belongs to controls.
- **Don't** add an uppercase line above a heading; uppercase is for tags and field names that carry data.
- **Don't** add rings, gauges or progress cards to show protein; the front's fill and the week bars carry it.
- **Don't** use colour alone for state; every state has a word or a number beside it.
