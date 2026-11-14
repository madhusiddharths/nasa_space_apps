# Design guide: the holographic look

Read this before changing anything the user sees. It describes the look the team agreed on
and the rules that keep it consistent when several people (and their AI assistants) work on
the frontend at once.

The look in one sentence: **a holographic heads-up display over Mars.** Dark glass panels,
thin cyan lines, bright corner brackets, spaced capitals for labels, and routes drawn as
lines of light.

## Ground rules

1. **Desktop only.** Design for a wide screen with mouse and keyboard. Do not add phone or
   tablet layouts.
2. **All styling lives in `web/theme.css`.** Do not put `<style>` blocks in JavaScript or in
   `index.html`, and do not hard-code colours or fonts in markup. If a new panel needs
   styles, add a section for it to `theme.css`.
3. **Use the tokens.** Every colour, font and glow comes from a `--holo-*` variable at the
   top of `theme.css`. If you need a new one, add it there with a comment; do not invent a
   one-off value.
4. **Colours drawn on the map come from `HOLO` in `web/routing.js`.** The map cannot read
   the stylesheet, so `HOLO` mirrors the tokens. Keep the two in step. Map tiles drawn by
   Python (for example `contours.py`) hold their own colour constants, copied from the tokens.
5. **Do not restyle the map imagery or the data layers' colour scales.** Their colours carry
   meaning and have legends. The look applies to the interface and to the route and contour
   lines, not to the science layers.
6. **No build step.** The frontend is plain HTML, CSS and JavaScript served from `web/`. Do
   not add a framework or bundler without the team agreeing.
7. **Keep the Esri credit line** at the bottom of the map. It is a terms-of-use requirement.

## Tokens

Defined in `:root` in `web/theme.css`.

| Token | Value | Use |
|---|---|---|
| `--holo-bg` | `rgba(5, 11, 17, 0.84)` | Panel glass |
| `--holo-bg-solid` | `#050b11` | Menus and anything that must be opaque |
| `--holo-raise` | cyan at 8% | Field backgrounds, quiet highlights |
| `--holo-raise-strong` | cyan at 18% | Hover |
| `--holo-line` | cyan at 26% | Hairlines and panel borders |
| `--holo-line-strong` | cyan at 60% | Button borders, section dividers |
| `--holo-cyan` | `#6fd3f2` | Labels, accents, icons |
| `--holo-bright` | `#e9fbff` | Values, headings, anything that should stand out |
| `--holo-text` | `#c6e2ee` | Body text |
| `--holo-dim` | `#86b3c6` | Hints and secondary text |
| `--holo-amber` | `#ffb000` | Caution, warnings |
| `--holo-red` | `#ff5a4a` | Danger, "not viable", errors |
| `--holo-magenta` | `#e86bff` | Extreme hazard |
| `--holo-glow` | soft cyan shadow | Headings, active buttons, headline numbers |
| `--holo-panel` | background shorthand | Glass plus the four corner brackets |

Amber, red and magenta mean hazard levels everywhere (Caution, Danger, Extreme). Never use
them for decoration.

## Type

- **Body:** Barlow, 13 px, regular. Numbers use tabular figures so columns line up.
- **Headings and labels:** Barlow Condensed, capitals, letter-spaced (`0.08em` to `0.12em`),
  weight 500. Panel titles are 16 px, bright, with the glow.
- **Headline numbers** (a route's total time): 26 px, bright, with the glow.
- Smallest text is 11 px. Write labels in normal sentence case in the HTML; the stylesheet
  turns them into capitals.

Fonts load from Google Fonts in `index.html`, with Segoe UI and the system font as fallbacks.

## Components

- **Panel:** `background: var(--holo-panel)`, a 1 px `--holo-line` border, square corners,
  a light backdrop blur. Esri panels and popups get this automatically; for your own
  container, add the class `holo-panel` or `legend`.
- **Button:** transparent, 1 px `--holo-line-strong` border, cyan capitals. Hover fills with
  `--holo-raise-strong`. A pressed or active button is filled cyan with dark text and the glow
  (`aria-pressed="true"`).
- **Field** (text, number, select): `--holo-raise` background, 1 px `--holo-line` border,
  bright text, square corners.
- **Data table:** label left in body text, value right in bright text, a hairline under each row.
- **Status line** (`.verdict`): `--holo-raise` background with a 2 px left edge in cyan, or
  in the hazard colour, or red when something is not viable.
- **Corners are square** everywhere. No rounded corners, no drop-shadowed cards, no gradients
  except data colour ramps.
- **Focus** must stay visible: a 1 px bright outline.

## On the map

- **Routes are lines of light.** Each is drawn by `addBeam` in `routing.js`, from the outside
  in: a wide faint glow, a dark casing, a tighter glow, the coloured core, a bright centre.
  Driven legs are solid; walked legs are dotted. Safest is cyan `#4fe3ff`, quickest is pale
  violet `#aab8ff`. Hazard stretches use amber, red and magenta.
- **Markers are diamonds** that float above the ground on a thin stem, with a small dot where
  the stem touches down (`addMarker` in `routing.js`). Use this for any new point of interest
  tied to a route.
- **Contour lines** take their colour from what is under them, so they always stand out
  (`STYLES` in `contours.py`, chosen by `contourStyle` in `index.html`):
  - holographic blue `rgb(63, 182, 224)` over bare dark ground, when the imagery and every
    data layer are off;
  - bright (`--holo-bright`) with a thin dark edge over the imagery and over data layers
    with dark colours (temperature, radiation);
  - dark (`--holo-bg-solid`) with a faint bright edge over data layers with light colours
    (water ice, topography, ground firmness).

  Labels follow the line: bright on a dark edge, or dark on a bright edge.
- **Bare ground is dark** (`surfaceColor` in `index.html`), so with the imagery switched off
  the overlays read as a holographic terrain model.
- **The layer stack, top down:** the route; marker and outline layers (traverses, feature
  names, craters); the contour lines; ONE data layer; the CTX imagery. The data layers are
  the coloured maps (temperature, radiation, water ice, topography, ground firmness).
  Switching one on switches the others off, so their colours never mix; none at all is
  allowed. Contours and imagery are each simply on or off. This is set up under "The layer
  stack" in `index.html`.

## Adding things

- **A new data layer** (a coloured map): build it with `serverTiles()` and add it to
  `DATA_LAYERS` in `index.html`. That gives it the one-at-a-time rule and its place under
  the contour lines. Add it to `CONTOUR_STYLE` too, saying whether light or dark contour
  lines read best over its colours. Give it a legend with the `legend` class, added with
  `addLegend` so it shows only while the layer does.
- **A new marker or outline layer:** build it with `GeoJSONLayer` and add it to the map; it
  draws above the contour lines.
- **A new panel:** build the HTML in its own `web/*.js` file, give the container an id, and
  add its styles as a new section in `theme.css` using the tokens and the components above.
  Copy the structure of `#routePanel`.
- **A new colour or font:** add a token first, and add it to the table above.

## Words

- Short labels, verb first on buttons ("Pick on map", "Clear route").
- Say what a number is and give its unit ("Rover range used: 92 of 125 km").
- State limits plainly ("Not viable: ...") and say why.

## Changing the look itself

A change to the tokens, the fonts, the panel shape or the route style changes the whole app.
Agree it with the team first, then update this file in the same commit.
