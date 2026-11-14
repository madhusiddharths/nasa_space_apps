# Notes for AI assistants working on this project

- Before changing anything the user sees (anything under `web/`, or the colours of map tiles
  drawn in Python), read `DESIGN.md` and follow it. The look is agreed by the team; do not
  change tokens, fonts, panel shapes or the route style unless the user asks for that.
- All styling goes in `web/theme.css`, using the `--holo-*` tokens. No `<style>` blocks in
  JavaScript or HTML, no hard-coded colours.
- Design for desktop only. Do not add phone or tablet layouts.
- The page layout is fixed: a rail of modes, one docked panel, the map, a status strip
  (`web/layout.js`). New controls go in the dock, not in floating widgets over the map.
- The frontend has no build step: plain files in `web/`, served by `server.py`.
- What the project is and how to run it: `README.md`. Where the data comes from: `DATA_SOURCES.md`.
