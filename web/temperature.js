// Surface temperature layer: map tiles and point readouts come from server.py
// (/temperature/tile, /temperature/point), which reads temperature.py.
// index.html calls addTemperatureLayer(map, view, { BaseTileLayer, Expand, tileInfo, fullExtent }).

function addTemperatureLayer(map, view, { BaseTileLayer, Expand, tileInfo, fullExtent }) {
  const MARS_WKID = 104971;
  // Colour stops and ranges must match RAMP and COLOR_RANGES in temperature.py.
  const RAMP = ["#0d0887", "#5402a3", "#8b0aa5", "#b93289", "#db5c68", "#f48849", "#febc2b", "#f0f921"];
  const MODES = {
    "": { label: "At this time", low: 150, high: 300, swing: false },
    min: { label: "Daily low", low: 150, high: 300, swing: false },
    max: { label: "Daily high", low: 150, high: 300, swing: false },
    range: { label: "Day-night swing", low: 0, high: 120, swing: true },
  };
  // Curiosity's traverse area: clicks here also show what REMS measured on the ground.
  const GALE = { west: 137.2, east: 137.6, south: -4.95, north: -4.4 };

  const state = { ls: 90, localTime: 14, stat: "", fit: null };   // fit = { low, high } colour range, or null = planet-wide

  // ---- The layer ----
  const tileUrl = (level, row, col) => {
    const fit = state.fit ? `&low=${state.fit.low}&high=${state.fit.high}` : "";
    return `/temperature/${level}/${row}/${col}.png?ls=${state.ls}&local_time=${state.localTime}&stat=${state.stat}${fit}`;
  };
  const TemperatureLayer = BaseTileLayer.createSubclass({
    // A tile that was requested before the sliders moved is fetched again, so the map never mixes settings.
    fetchTile(level, row, col, options) {
      const url = tileUrl(level, row, col);
      return new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => reject(new Error("temperature tile failed: " + url));
        if (options && options.signal) options.signal.addEventListener("abort", () => { image.src = ""; reject(new DOMException("aborted", "AbortError")); });
        image.src = url;
      }).then((image) => (url === tileUrl(level, row, col) ? image : this.fetchTile(level, row, col, options)));
    },
  });
  const layer = new TemperatureLayer({
    title: "Surface Temperature (THEMIS + TES thermal model)",
    copyright: "Thermal inertia: NASA/JPL/ASU/USGS (THEMIS). Albedo: NASA/JPL/ASU (TES). Ground truth: NASA/JPL/CAB (REMS)",
    visible: false,
    opacity: 0.65,
    spatialReference: { wkid: MARS_WKID },
    fullExtent,
    tileInfo,                                     // same scheme as the CTX imagery and the terrain
  });
  map.add(layer);

  // ---- Helpers ----
  const celsius = (k) => Math.round(k - 273.15);
  const both = (k) => `${celsius(k)} °C (${Math.round(k)} K)`;
  const clock = (h) => `${String(Math.floor(h)).padStart(2, "0")}:${h % 1 ? "30" : "00"}`;
  const SEASONS = ["spring", "summer", "autumn", "winter"];
  const season = (ls) => {
    const q = Math.floor((ls % 360) / 90);
    return `north ${SEASONS[q]}, south ${SEASONS[(q + 2) % 4]}`;
  };
  const ground = (ti) =>
    ti < 150 ? "loose dust" : ti < 250 ? "fine sand" : ti < 400 ? "coarse sand, some crust" :
    ti < 700 ? "gravel and rocky ground" : "rock and bedrock";

  // ---- Panel ----
  const style = document.createElement("style");
  style.textContent = `
    #tempPanel { width: 290px; padding: 12px; font-size: 13px; line-height: 1.4; max-height: calc(100vh - 150px); overflow-y: auto; box-sizing: border-box; }
    #tempPanel h3 { margin: 0 0 8px; font-size: 15px; font-weight: 600; }
    #tempPanel label { display: block; margin-top: 10px; }
    #tempPanel label span { float: right; opacity: 0.75; }
    #tempPanel input[type=range] { width: 100%; margin: 2px 0 0; }
    #tempPanel .modes { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; margin-top: 10px; }
    #tempPanel .modes button { padding: 5px 2px; border: 1px solid #555; background: none; color: inherit; cursor: pointer; border-radius: 3px; font: inherit; }
    #tempPanel .modes button[aria-pressed=true] { background: #d1d1d1; color: #242424; border-color: #d1d1d1; }
    #tempPanel .ramp { height: 12px; margin-top: 12px; border-radius: 2px; background: linear-gradient(to right, ${RAMP.join(",")}); }
    #tempPanel .ticks { display: flex; justify-content: space-between; font-size: 11px; opacity: 0.75; }
    #tempPanel .readout { margin-top: 12px; padding-top: 10px; border-top: 1px solid #444; }
    #tempPanel .readout table { width: 100%; border-collapse: collapse; }
    #tempPanel .readout td { padding: 1px 0; }
    #tempPanel .readout td:last-child { text-align: right; }
    #tempPanel .hint { opacity: 0.7; }
    #tempPanel svg { display: block; margin-top: 8px; width: 100%; height: auto; }
    #tempPanel svg text { fill: currentColor; font-size: 10px; opacity: 0.7; }
    #tempPanel .tip { min-height: 1.4em; font-size: 12px; }
  `;
  document.head.appendChild(style);

  const panel = document.createElement("div");
  panel.id = "tempPanel";
  panel.className = "esri-widget esri-widget--panel";
  panel.innerHTML = `
    <h3>Surface temperature</h3>
    <label style="margin-top:0"><input type="checkbox" id="tempShow"> Show on map</label>
    <label>Season <span id="tempLsText"></span>
      <input type="range" id="tempLs" min="0" max="345" step="15" value="${state.ls}"></label>
    <label>Local solar time <span id="tempTimeText"></span>
      <input type="range" id="tempTime" min="0" max="23.5" step="0.5" value="${state.localTime}"></label>
    <div class="modes" role="group" aria-label="What the map shows">
      ${Object.entries(MODES).map(([k, m]) => `<button data-stat="${k}">${m.label}</button>`).join("")}
    </div>
    <label>Opacity <input type="range" id="tempOpacity" min="0.1" max="1" step="0.05" value="${layer.opacity}"></label>
    <div class="ramp"></div>
    <div class="ticks" id="tempTicks"></div>
    <div class="modes" style="margin-top:8px">
      <button id="tempFit" title="Stretch the colours over the temperatures in the area you are looking at">Fit colours to view</button>
      <button id="tempUnfit" title="Use the same colours everywhere on the planet">Planet-wide colours</button>
    </div>
    <div class="readout" id="tempReadout"><span class="hint">Turn the layer on and click the ground for a 24-hour forecast of that spot.</span></div>
  `;
  view.ui.add(new Expand({ view, content: panel, expandIconClass: "esri-icon-environment-settings",
                           expandTooltip: "Surface temperature", expanded: false }), "top-right");

  const $ = (id) => panel.querySelector("#" + id);
  let lastPoint = null;
  let refreshTimer = null;

  function render() {
    const mode = state.fit ? { ...MODES[state.stat], ...state.fit } : MODES[state.stat];
    $("tempLsText").textContent = `Ls ${state.ls}°, ${season(state.ls)}`;
    $("tempTimeText").textContent = state.stat ? "whole day" : clock(state.localTime);
    $("tempTime").disabled = !!state.stat;
    panel.querySelectorAll(".modes button[data-stat]").forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.stat === state.stat)));
    $("tempFit").setAttribute("aria-pressed", String(!!state.fit));
    $("tempUnfit").setAttribute("aria-pressed", String(!state.fit));
    const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => mode.low + f * (mode.high - mode.low));
    $("tempTicks").innerHTML = ticks.map((k) =>
      `<span>${mode.swing ? Math.round(k) : celsius(k)} °C</span>`).join("");
  }
  function changed(refetchPoint) {
    render();
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => layer.refresh(), 150);
    if (lastPoint) refetchPoint ? readPoint(lastPoint.lon, lastPoint.lat) : drawReadout();
  }

  $("tempShow").addEventListener("change", (e) => { layer.visible = e.target.checked; });
  layer.watch("visible", (v) => { $("tempShow").checked = v; });
  $("tempLs").addEventListener("input", (e) => { state.ls = +e.target.value; changed(true); });
  $("tempTime").addEventListener("input", (e) => { state.localTime = +e.target.value; changed(false); });
  $("tempOpacity").addEventListener("input", (e) => { layer.opacity = +e.target.value; });
  panel.querySelectorAll(".modes button[data-stat]").forEach((b) =>
    b.addEventListener("click", () => { state.stat = b.dataset.stat; state.fit ? fitToView() : changed(false); }));

  // Colour range from the temperatures around the centre of the view.
  function fitToView() {
    const c = view.center, half = Math.min(60, Math.max(0.05, (view.extent ? view.extent.width : 2) / 4));
    const q = `west=${Math.max(-180, c.longitude - half)}&east=${Math.min(180, c.longitude + half)}` +
              `&south=${Math.max(-90, c.latitude - half)}&north=${Math.min(90, c.latitude + half)}`;
    fetch(`/temperature/range?${q}&ls=${state.ls}&local_time=${state.localTime}&stat=${state.stat}`)
      .then((r) => r.json())
      .then((range) => { state.fit = range; changed(false); })
      .catch((e) => console.error(e));
  }
  $("tempFit").addEventListener("click", fitToView);
  $("tempUnfit").addEventListener("click", () => { state.fit = null; changed(false); });

  // ---- Click readout: the 24-hour cycle at one spot ----
  let rems = null;
  fetch("data/rems_ground_temperature.json").then((r) => r.json()).then((d) => { rems = d; }).catch(() => {});

  function chart(kelvin) {
    const W = 266, H = 120, L = 30, R = 6, T = 8, B = 18;
    const lo = Math.floor((Math.min(...kelvin) - 273.15) / 20) * 20;
    const hi = Math.ceil((Math.max(...kelvin) - 273.15) / 20) * 20;
    const x = (h) => L + (h / 24) * (W - L - R);
    const y = (k) => T + (1 - (k - 273.15 - lo) / (hi - lo)) * (H - T - B);
    const cycle = kelvin.concat(kelvin[0]);              // hour 24 = hour 0
    const path = cycle.map((k, h) => `${h ? "L" : "M"}${x(h).toFixed(1)},${y(k).toFixed(1)}`).join("");
    const grid = [lo, (lo + hi) / 2, hi].map((c) =>
      `<line x1="${L}" x2="${W - R}" y1="${y(c + 273.15)}" y2="${y(c + 273.15)}" stroke="currentColor" stroke-opacity="0.15"/>
       <text x="${L - 4}" y="${y(c + 273.15) + 3}" text-anchor="end">${c}°</text>`).join("");
    const hours = [0, 6, 12, 18, 24].map((h) => `<text x="${x(h)}" y="${H - 4}" text-anchor="middle">${h}h</text>`).join("");
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Surface temperature through the day, in degrees Celsius">
      ${grid}${hours}
      <path d="${path}" fill="none" stroke="#f48849" stroke-width="2" stroke-linejoin="round"/>
      <line id="tempNow" y1="${T}" y2="${H - B}" stroke="currentColor" stroke-opacity="0.6" stroke-dasharray="3 3"/>
      <circle id="tempDot" r="4" fill="#f48849" stroke="#242424" stroke-width="2"/>
      <rect id="tempHit" x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent"/>
    </svg><div class="tip" id="tempTip"></div>`;
  }

  function drawReadout() {
    const p = lastPoint;
    const box = $("tempReadout");
    const inGale = p.lon > GALE.west && p.lon < GALE.east && p.lat > GALE.south && p.lat < GALE.north;
    const measured = inGale && rems && rems.bins.find((b) => b.ls_from <= state.ls && state.ls < b.ls_to);
    box.innerHTML = `
      <table>
        <tr><td>Location</td><td>${p.lat.toFixed(4)}°N, ${p.lon.toFixed(4)}°E</td></tr>
        <tr><td>Daily low</td><td>${both(p.min)}</td></tr>
        <tr><td>Daily high</td><td>${both(p.max)}</td></tr>
        <tr><td>Ground</td><td>${ground(p.thermal_inertia)}</td></tr>
        <tr><td>Thermal inertia</td><td>${Math.round(p.thermal_inertia)} J m⁻² K⁻¹ s⁻½</td></tr>
        <tr><td>Albedo</td><td>${p.albedo.toFixed(2)}</td></tr>
        ${measured ? `<tr><td colspan="2" style="padding-top:6px">Curiosity measured here in this season (REMS, ${measured.sols} sols):</td></tr>
        <tr><td>Ground low / high</td><td>${celsius(measured.ground_min)} / ${celsius(measured.ground_max)} °C</td></tr>
        <tr><td>Air low / high</td><td>${celsius(measured.air_min)} / ${celsius(measured.air_max)} °C</td></tr>` : ""}
      </table>${chart(p.kelvin_by_hour)}`;

    const at = (h) => {                                  // linear between whole hours, wrapping at midnight
      const k = p.kelvin_by_hour, i = Math.floor(h) % 24, f = h - Math.floor(h);
      return k[i] * (1 - f) + k[(i + 1) % 24] * f;
    };
    const svg = box.querySelector("svg"), W = 266, L = 30, R = 6;
    const lo = Math.floor((p.min - 273.15) / 20) * 20, hi = Math.ceil((p.max - 273.15) / 20) * 20;
    const place = (h) => {
      const px = L + (h / 24) * (W - L - R);
      const py = 8 + (1 - (at(h) - 273.15 - lo) / (hi - lo)) * (120 - 8 - 18);
      svg.querySelector("#tempNow").setAttribute("x1", px);
      svg.querySelector("#tempNow").setAttribute("x2", px);
      svg.querySelector("#tempDot").setAttribute("cx", px);
      svg.querySelector("#tempDot").setAttribute("cy", py);
      $("tempTip").textContent = `${clock(Math.round(h * 2) / 2 % 24)} local: ${both(at(h))}`;
    };
    place(state.localTime);
    const hit = svg.querySelector("#tempHit");
    hit.addEventListener("pointermove", (e) => {
      const r = hit.getBoundingClientRect();
      place(Math.max(0, Math.min(23.99, ((e.clientX - r.left) / r.width) * 24)));
    });
    hit.addEventListener("pointerleave", () => place(state.localTime));
  }

  function readPoint(lon, lat) {
    fetch(`/temperature/point?lon=${lon}&lat=${lat}&ls=${state.ls}`)
      .then((r) => r.json())
      .then((p) => { lastPoint = p; drawReadout(); })
      .catch((e) => console.error(e));
  }

  view.on("click", (event) => {
    const where = layer.visible && clickedGroundPoint(event);   // from picking.js
    if (where) readPoint(where.longitude, where.latitude);
  });

  render();
  return { layer, state, readPoint };
}
