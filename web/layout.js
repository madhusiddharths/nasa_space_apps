// The page layout around the map: a rail of modes down the left edge, one docked panel
// beside it that shows the chosen mode, and a status strip along the bottom.
// (Legends and the map controls are placed on the map itself, in index.html.)
//
// index.html calls addDock() first, so every panel has a place to go, and addStatusBar(view)
// once the view exists. All of it is styled in theme.css.

// How a position is written everywhere in the interface: "4.590°S, 137.442°E".
const formatPosition = (lon, lat) => `${Math.abs(lat).toFixed(3)}°${lat < 0 ? "S" : "N"}, ${lon.toFixed(3)}°E`;

// The modes, in rail order: key, label under the icon, Esri icon class, panel title for screen readers.
const DOCK_MODES = [
  ["route", "Route", "esri-icon-directions", "Route planner"],
  ["layers", "Layers", "esri-icon-layers", "Map layers"],
  ["temperature", "Temp", "esri-icon-environment-settings", "Surface temperature"],
  ["places", "Places", "esri-icon-map-pin", "Places"],
  ["tools", "Tools", "esri-icon-measure-area", "Coordinates and measuring tools"],
];

// Builds the rail and the empty panels. Returns:
//   panel(mode)           the element that holds a mode's content
//   slot(mode, heading)   a new titled section inside a mode's panel; returns its body element
//   show(mode)            opens a mode; show(null) closes the dock, giving the map the full width
function addDock(startMode = "route") {
  const rail = document.getElementById("rail"), dock = document.getElementById("dock");
  rail.innerHTML = `<div class="mark" title="Interplanetary Survival Guide: Mars"><span>M</span></div>` +
    DOCK_MODES.map(([mode, label, icon, title]) =>
      `<button data-mode="${mode}" title="${title}" aria-pressed="false"><span class="${icon}" aria-hidden="true"></span>${label}</button>`).join("");
  dock.innerHTML = DOCK_MODES.map(([mode, , , title]) =>
    `<section data-mode="${mode}" aria-label="${title}" hidden></section>`).join("");

  const panel = (mode) => dock.querySelector(`section[data-mode="${mode}"]`);
  let current = null;
  function show(mode) {
    current = mode;
    dock.hidden = !mode;
    for (const section of dock.children) section.hidden = section.dataset.mode !== mode;
    for (const button of rail.querySelectorAll("button")) button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
  }
  // Clicking the open mode again closes the dock.
  rail.addEventListener("click", (e) => {
    const button = e.target.closest("button[data-mode]");
    if (button) show(button.dataset.mode === current ? null : button.dataset.mode);
  });

  function slot(mode, heading) {
    const section = document.createElement("div");
    section.className = "slot";
    section.innerHTML = `<h3>${heading}</h3><div></div>`;
    panel(mode).appendChild(section);
    return section.lastElementChild;
  }

  show(startMode);
  return { panel, slot, show };
}

// The status strip: what is under the cursor (position, elevation), how high the camera is,
// and for the last spot clicked the day's ground temperature and the radiation dose.
// picking is what addGroundPicking returned; season() gives the solar longitude to read
// temperatures for; radiationAt(lon, lat) resolves to the radiation values at a spot, or null.
function addStatusBar(view, { picking, season, radiationAt }) {
  const bar = document.getElementById("statusBar");
  const item = (key, label) => `<span class="item"><span class="label">${label}</span><span data-key="${key}">–</span></span>`;
  bar.innerHTML = item("position", "Cursor") + item("elevation", "Elevation") + item("height", "View height") +
    item("ground", "Ground, day") + item("dose", "Radiation") +
    `<span class="brand">Interplanetary Survival Guide<b>Mars</b></span>`;
  const set = (key, text) => { bar.querySelector(`[data-key="${key}"]`).textContent = text; };

  const metres = (m) => `${Math.round(m).toLocaleString("en-US").replace(/,/g, " ").replace("-", "−")} m`;
  const celsius = (k) => `${Math.round(k - 273.15)}`.replace("-", "−");

  // Under the cursor: at most one lookup per frame.
  let pending = null;
  view.on("pointer-move", (event) => {
    const first = !pending;
    pending = { x: event.x, y: event.y };
    if (!first) return;
    requestAnimationFrame(() => {
      const where = picking.groundPoint(pending.x, pending.y);
      pending = null;
      set("position", where ? formatPosition(where.longitude, where.latitude) : "–");
      set("elevation", where ? metres(picking.elevation(where.longitude, where.latitude)) : "–");
    });
  });
  view.on("pointer-leave", () => { set("position", "–"); set("elevation", "–"); });

  view.watch("camera", (camera) => {
    const z = camera.position.z;
    set("height", z >= 10000 ? `${Math.round(z / 1000).toLocaleString("en-US").replace(/,/g, " ")} km` : metres(z));
  });

  // The clicked spot: values that need the server, so they are read on a click, not on every move.
  let request = 0;
  view.on("click", (event) => {
    const where = clickedGroundPoint(event);     // from picking.js
    if (!where) return;
    const id = ++request, at = `lon=${where.longitude}&lat=${where.latitude}`;
    set("ground", "…");
    set("dose", "…");
    fetch(`/temperature/point?${at}&ls=${season()}`).then((r) => (r.ok ? r.json() : null))
      .then((p) => { if (id === request) set("ground", p ? `${celsius(p.min)} to ${celsius(p.max)} °C` : "–"); })
      .catch(() => { if (id === request) set("ground", "–"); });
    radiationAt(where.longitude, where.latitude)
      .then((p) => { if (id === request) set("dose", p ? `${p.dose_eq_msv_per_day.toFixed(2)} mSv/day` : "–"); })   // modelled inside Gale crater only
      .catch(() => { if (id === request) set("dose", "–"); });
  });
}
