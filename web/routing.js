// Astronaut route planner: set A and B, get the safest and the quickest trip by rover and on foot.
// A and B are set by searching (a place name, a CTX grid tile, or coordinates in any of the
// coordinate widget's formats) or by picking them on the map.
// The routes come from server.py (/routing/astronaut), which runs routing.py.
// index.html calls addRouting(map, view, { GraphicsLayer, GroupLayer, Graphic, container, coordinateFormatter, selectedFormat });
// the panel is put inside `container` (the dock's route panel).
// The panel is styled in theme.css; the colours drawn on the map are in HOLO below.

function addRouting(map, view, { GraphicsLayer, GroupLayer, Graphic, container, coordinateFormatter, selectedFormat }) {
  const MARS_WKID = 104971;
  // Colours drawn on the map and set inline in the panel; they mirror the tokens in theme.css.
  const HOLO = { glass: [5, 11, 17], bright: "#e9fbff", cyan: "#6fd3f2", amber: "#ffb000", red: "#ff5a4a", magenta: "#e86bff" };
  const ROUTES = {
    safest: { label: "Safest", color: "#4fe3ff" },
    quickest: { label: "Quickest", color: "#aab8ff" },
  };
  // Hazard levels as routing.py numbers them: 0 Clear, 1 Caution, 2 Danger, 3 Extreme.
  const LEVELS = ["Clear", "Caution", "Danger", "Extreme"];
  const LEVEL_COLORS = [null, HOLO.amber, HOLO.red, HOLO.magenta];
  const BAD = HOLO.red;
  const SEASONS = [[0, "Northern spring"], [90, "Northern summer"], [180, "Northern autumn"], [270, "Northern winter"]];
  const MODES = { drive: "driving", walk: "walking" };

  const state = {
    start: null, end: null, names: { start: "", end: "" }, picking: null,
    ls: 90, localTime: 12, rangeKm: 125, maxWalkKm: 10,       // the last two are replaced by routing.py's defaults
    shown: { safest: true, quickest: true }, result: null,
  };

  // Lines lie on the ground; markers float above it on a thin stem.
  const layer = new GraphicsLayer({ title: "Route lines", elevationInfo: { mode: "on-the-ground" } });
  const markers = new GraphicsLayer({ title: "Route markers", elevationInfo: { mode: "relative-to-ground" } });
  const group = new GroupLayer({ title: "Astronaut Route", layers: [layer, markers], listMode: "hide-children" });
  map.add(group);

  // ---- Panel (styled in theme.css) ----

  const placeRow = (letter, which, what) => `
    <div class="place">
      <b><span>${letter}</span></b>
      <input type="text" id="routeSearch${letter}" data-which="${which}" autocomplete="off" spellcheck="false"
             placeholder="Place, grid tile or coordinates" aria-label="${what}: search by place name, grid tile or coordinates">
      <button id="routePick${letter}" title="Then click the map where the trip ${which === "start" ? "starts" : "ends"}">Pick on map</button>
    </div>
    <div class="suggest" id="routeSuggest${letter}" hidden></div>`;

  const panel = document.createElement("div");
  panel.id = "routePanel";
  panel.className = "esri-widget";
  panel.innerHTML = `
    <h3>Astronaut route</h3>
    ${placeRow("A", "start", "Start")}
    ${placeRow("B", "end", "Destination")}
    <div class="points" id="routePoints"></div>
    <div class="row">
      <label class="field">Rover range on flat ground, km
        <input type="number" id="routeRange" min="1" step="5"></label>
      <label class="field">Most walking allowed, km
        <input type="number" id="routeWalk" min="0.5" step="0.5"></label>
    </div>
    <div class="row">
      <select id="routeSeason" aria-label="Season">
        ${SEASONS.map(([ls, name]) => `<option value="${ls}">${name}</option>`).join("")}
      </select>
      <select id="routeTime" aria-label="Departure, local solar time">
        ${Array.from({ length: 24 }, (_, h) => `<option value="${h}">Leave ${String(h).padStart(2, "0")}:00</option>`).join("")}
      </select>
    </div>
    <div id="routeResult"><div class="hint" style="margin-top:10px">Set a start and a destination: type a crater or
      feature name, a grid tile (such as E136_N-08) or coordinates, or pick the point on the map.
      The map then shows the safest and the quickest trip, driven as far as the rover can go and walked the rest.</div></div>
    <div class="row"><button id="routeClear">Clear route</button></div>
    <div class="note" id="routeNote"></div>
  `;
  container.appendChild(panel);

  const $ = (id) => panel.querySelector("#" + id);
  $("routeSeason").value = state.ls;
  $("routeTime").value = state.localTime;
  $("routeRange").value = state.rangeKm;
  $("routeWalk").value = state.maxWalkKm;

  const note = (n) => {
    $("routeNote").innerHTML = `
Lines of light: solid by rover, dotted on foot. P: where the rover is boarded or parked
      (level, firm ground that is easy to drive into and walk away from).
      Hazards on the lines: <span style="color:${LEVEL_COLORS[1]}">Caution</span>,
      <span style="color:${LEVEL_COLORS[2]}">Danger</span>, <span style="color:${LEVEL_COLORS[3]}">Extreme</span>;
      thick with a white edge where no route can avoid them.
      ${n ? `Rover: ${n.rover_kmh} km/h on flat firm ground, slower and using more of its range on climbs and
      soft ground; it does not drive slopes over ${n.rover_slope_deg[2]}° and parks on ${n.park_slope_deg}° or less.
      On foot: ${n.walk_kmh} km/h. The longest walk made on another world is about ${n.record_walk_km} km (Apollo 14);
      ${n.max_walk_km} km is the walk-back distance NASA has studied. One way only. ${n.note}` : ""}`;
  };
  note(null);
  // Defaults and the numbers in the note come from routing.py.
  fetch("/routing/legend").then((r) => r.json()).then((n) => {
    if (+$("routeRange").value === state.rangeKm) $("routeRange").value = state.rangeKm = n.rover_range_km;
    if (+$("routeWalk").value === state.maxWalkKm) $("routeWalk").value = state.maxWalkKm = n.max_walk_km;
    note(n);
  }).catch(() => {});

  // ---- Helpers ----
  const duration = (minutes) => (minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")} min`);
  const length = (m) => (m < 1000 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1)} km`);
  const position = (p) => `${Math.abs(p[1]).toFixed(3)}°${p[1] < 0 ? "S" : "N"}, ${p[0].toFixed(3)}°E`;
  const wrap = (lon) => +(((lon + 180) % 360 + 360) % 360 - 180).toFixed(7);
  const escapeHtml = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // ---- Search: coordinates ----
  // "4.59S 137.44E", "Lat: -4.59°N, Long: 137.44°E", "4°35'22"S 137°26'30"E", "-4.59, 137.44":
  // two values of 1 to 3 numbers each (degrees, minutes, seconds), each with an optional N/S/E/W.
  // Without letters the first value is the latitude, unless the coordinate widget is set to
  // BASEMAP (x, y) or the first value cannot be a latitude.
  function parseLatLon(text) {
    const upper = text.toUpperCase();
    const latWord = upper.search(/LAT/), lonWord = upper.search(/LON/);
    const bare = upper.replace(/LONGITUDE|LATITUDE|LONG|LON|LAT|DEG/g, " ");
    if (/[A-DF-MO-RT-VX-Z_]/.test(bare)) return null;        // other letters: a name; "_": a grid tile
    const tokens = bare.match(/[-+]?\d+(?:\.\d+)?|[NSEW]/g) || [];
    const numbers = tokens.filter((t) => !/[NSEW]/.test(t));
    const letters = tokens.filter((t) => /[NSEW]/.test(t));
    if (![2, 4, 6].includes(numbers.length) || ![0, 2].includes(letters.length)) return null;
    const half = numbers.length / 2;
    const value = (parts, letter) => {
      const [d, m = 0, s = 0] = parts.map((n) => Math.abs(parseFloat(n)));
      const sign = (parts[0].trim().startsWith("-") ? -1 : 1) * (letter === "S" || letter === "W" ? -1 : 1);
      return sign * (d + m / 60 + s / 3600);
    };
    const first = value(numbers.slice(0, half), letters[0]), second = value(numbers.slice(half), letters[1]);
    let latFirst;
    if (letters.length) {
      if (/[NS]/.test(letters[0]) === /[NS]/.test(letters[1])) return null;
      latFirst = /[NS]/.test(letters[0]);
    } else if (latWord >= 0 && lonWord >= 0) latFirst = latWord < lonWord;
    else if (selectedFormat && selectedFormat() === "basemap") latFirst = false;
    else latFirst = Math.abs(first) <= 90;
    const [lat, lon] = latFirst ? [first, second] : [second, first];
    if (Math.abs(lat) > 90 || Math.abs(lon) > 360) return null;
    return [wrap(lon), lat];
  }

  // MGRS, USNG and UTM strings, read the way the coordinate widget writes them.
  const formatterReady = coordinateFormatter ? Promise.resolve(coordinateFormatter.load()).then(() => true, () => false) : Promise.resolve(false);
  function parseGrid(text) {
    const t = text.trim().toUpperCase();
    const mgrs = /^\d{1,2}\s*[C-HJ-NP-X]\s*[A-HJ-NP-Z]{2}\s*[\d\s]+$/.test(t);
    const utm = /^\d{1,2}\s*[C-HJ-NP-X]\s+\d+(\.\d+)?\s+\d+(\.\d+)?$/.test(t);
    if (!mgrs && !utm) return Promise.resolve(null);
    return formatterReady.then((ready) => {
      if (!ready) return null;
      const sr = view.spatialReference;
      const tries = utm ? [() => coordinateFormatter.fromUtm(t, sr, "latitude-band-indicators")]
                        : [() => coordinateFormatter.fromMgrs(t, sr, "automatic"), () => coordinateFormatter.fromUsng(t, sr)];
      for (const attempt of tries) {
        try {
          const p = attempt();
          if (p && Number.isFinite(p.x) && Number.isFinite(p.y)) return [wrap(p.x), p.y];
        } catch (e) { /* not this format */ }
      }
      return null;
    });
  }

  // ---- Search: names (IAU features, among them every named crater) and CTX grid tiles ----
  const fold = (s) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[\s_]+/g, " ").trim();
  let places = null;                               // loaded the first time a search box is used
  function loadPlaces() {
    if (places) return places;
    const features = (url) => fetch(url).then((r) => r.json()).then((d) => d.features).catch(() => []);
    places = Promise.all([features("data/mars-nomenclature.geojson"), features("data/MurrayLab_CTX_V01_Quad-Map.geojson")])
      .then(([named, tiles]) => [
        ...named.map((f) => {
          const p = f.properties, kind = (p.type || "Feature").split(",")[0];
          return { name: p.name, key: fold(p.clean_name || p.name),
                   detail: kind + (p.diameter ? `, ${Math.round(p.diameter)} km` : ""),
                   at: [wrap(p.center_lon), p.center_lat] };
        }),
        ...tiles.map((f) => {
          const ring = f.geometry.coordinates[0], xs = ring.map((c) => c[0]), ys = ring.map((c) => c[1]);
          return { name: f.properties.Quad, key: fold(f.properties.Quad), detail: "grid tile",
                   at: [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2] };
        }),
      ].filter((p) => p.name && Number.isFinite(p.at[0]) && Number.isFinite(p.at[1])));
    return places;
  }
  // Best matches first: the name itself, names starting with the text, a word starting with it, then anywhere.
  function matches(list, text, limit = 8) {
    const q = fold(text);
    if (!q) return [];
    const rank = (key) => (key === q ? 0 : key.startsWith(q) ? 1 : key.includes(" " + q) ? 2 : key.includes(q) ? 3 : -1);
    return list.map((p) => [rank(p.key), p]).filter(([r]) => r >= 0)
      .sort((x, y) => x[0] - y[0] || x[1].key.length - y[1].key.length).slice(0, limit).map(([, p]) => p);
  }

  // What a piece of text points at: coordinates, a grid reference, or the best-matching name.
  // Resolves to { at: [lon, lat], name } or null. Used by the Places panel too.
  function find(text) {
    const coords = parseLatLon(text);
    if (coords) return Promise.resolve({ at: coords, name: "" });
    return parseGrid(text).then((grid) => (grid ? { at: grid, name: text.trim().toUpperCase() }
      : loadPlaces().then((all) => matches(all, text, 1)[0] || null)));
  }

  // A search box: suggestions while typing, Enter takes coordinates or the first suggestion.
  function addSearch(letter, which) {
    const input = $("routeSearch" + letter), list = $("routeSuggest" + letter);
    let found = [], selected = -1;
    const close = () => { list.hidden = true; found = []; selected = -1; };
    const message = (text) => { list.hidden = false; list.innerHTML = `<div class="hint" style="cursor:default">${text}</div>`; found = []; };
    const render = () => {
      list.hidden = !found.length;
      list.innerHTML = found.map((p, i) =>
        `<div data-i="${i}" role="option" aria-selected="${i === selected}">${escapeHtml(p.name)}<small>${escapeHtml(p.detail)}</small></div>`).join("");
    };
    const choose = (p) => { close(); setPoint(which, p.at[0], p.at[1], p.name, true); };
    const suggest = () => {
      const text = input.value;
      if (parseLatLon(text)) return close();
      loadPlaces().then((all) => {
        if (input.value !== text) return;
        found = matches(all, text);
        selected = -1;
        render();
      });
    };
    const submit = () => {
      const text = input.value.trim();
      if (!text) return;
      if (selected >= 0 && found[selected]) return choose(found[selected]);
      const coords = parseLatLon(text);
      if (coords) { close(); return setPoint(which, coords[0], coords[1], "", true); }
      parseGrid(text).then((grid) => {
        if (grid) { close(); return setPoint(which, grid[0], grid[1], text.toUpperCase(), true); }
        return loadPlaces().then((all) => {
          const best = matches(all, text, 1)[0];
          if (best) choose(best);
          else message("Nothing found. Try a crater or feature name, a grid tile, or coordinates.");
        });
      });
    };
    input.addEventListener("focus", loadPlaces);
    input.addEventListener("input", suggest);
    input.addEventListener("blur", () => setTimeout(close, 150));
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); submit(); }
      else if (e.key === "Escape") close();
      else if ((e.key === "ArrowDown" || e.key === "ArrowUp") && found.length) {
        e.preventDefault();
        selected = (selected + (e.key === "ArrowDown" ? 1 : -1) + found.length + (selected < 0 && e.key === "ArrowUp" ? 1 : 0)) % found.length;
        render();
      }
    });
    list.addEventListener("mousedown", (e) => {
      const item = e.target.closest("[data-i]");
      if (item) { e.preventDefault(); choose(found[+item.dataset.i]); }
    });
    return input;
  }
  const inputs = { start: addSearch("A", "start"), end: addSearch("B", "end") };

  // ---- Drawing ----
  const polyline = (line) => ({ type: "polyline", paths: [line], spatialReference: { wkid: MARS_WKID } });
  const stroke = (color, width, lineStyle = "solid") => ({ type: "simple-line", color, width, style: lineStyle, cap: "round", join: "round" });
  const addLine = (line, color, width, extra = {}, lineStyle) =>
    layer.add(new Graphic({ geometry: polyline(line), symbol: stroke(color, width, lineStyle), ...extra }));
  const rgba = (hex, alpha) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).concat(alpha);

  // A line of light, from the outside in: a wide faint glow, a dark casing so it reads on
  // any ground, a tighter and stronger glow, the coloured core, and a bright centre.
  // Walked lines are dotted and have no centre.
  function addBeam(line, color, { dotted = false, width = 3, extra = {} } = {}) {
    addLine(line, rgba(color, 0.18), width + 16);
    addLine(line, [...HOLO.glass, 0.6], width + 8);
    addLine(line, rgba(color, 0.5), width + 6);
    addLine(line, color, width, extra, dotted ? "short-dot" : "solid");
    if (!dotted) addLine(line, [255, 255, 255, 0.95], 1.5);
  }

  // A marker: a diamond with a letter, floating above the ground on a thin stem, and a
  // small dot where the stem meets the ground.
  const diamond = (letter, filled) => "data:image/svg+xml," + encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
      <path d="M32 3 61 32 32 61 3 32Z" fill="${filled ? HOLO.cyan : "#050b11"}" fill-opacity="${filled ? 0.92 : 0.85}" stroke="${HOLO.bright}" stroke-width="3"/>
      <path d="M32 12 52 32 32 52 12 32Z" fill="none" stroke="${filled ? "#050b11" : HOLO.cyan}" stroke-opacity="0.45" stroke-width="1.5"/>
      <text x="32" y="41.5" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="25" font-weight="700" fill="${filled ? "#050b11" : HOLO.bright}">${letter}</text>
    </svg>`);
  function addMarker(p, letter, { filled = false, size = 28, extra = {} } = {}) {
    const geometry = { type: "point", x: p[0], y: p[1], spatialReference: { wkid: MARS_WKID } };
    layer.add(new Graphic({ geometry, symbol: { type: "simple-marker", color: HOLO.bright, size: 6, outline: { color: [...HOLO.glass, 0.9], width: 1.5 } } }));
    markers.add(new Graphic({
      geometry,
      symbol: {
        type: "point-3d",
        symbolLayers: [{ type: "icon", resource: { href: diamond(letter, filled) }, size }],
        verticalOffset: { screenLength: 34, maxWorldLength: 500000, minWorldLength: 0 },
        callout: { type: "line", size: 1, color: rgba(HOLO.bright, 0.9), border: { color: [...HOLO.glass, 0.6] } },
      },
      ...extra,
    }));
  }

  function draw() {
    layer.removeAll();
    markers.removeAll();
    const routes = state.result ? state.result.routes : {};
    // Quickest first, so the safest line stays on top where the two share ground.
    for (const name of ["quickest", "safest"]) {
      const route = routes[name];
      if (!route || !state.shown[name] || (name === "quickest" && route.same_as_safest && state.shown.safest)) continue;
      for (const leg of route.legs) {
        addBeam(route.line.slice(leg.from, leg.to + 1), ROUTES[name].color, { dotted: leg.mode === "walk" });
      }
      for (const s of route.stretches) {
        const part = route.line.slice(s.from, s.to + 1);
        if (s.unavoidable) addLine(part, [255, 255, 255, 0.9], 10);
        addBeam(part, LEVEL_COLORS[s.level], {
          dotted: s.mode === "walk", width: s.unavoidable ? 5 : 3,
          extra: {
            attributes: { hazards: s.hazards.join("; "), length: length(s.distance_m), time: duration(Math.round(s.minutes)) },
            popupTemplate: {
              title: `${LEVELS[s.level]}${s.unavoidable ? ", unavoidable" : ""} (${ROUTES[name].label.toLowerCase()} route)`,
              content: `{hazards}<br>{length}, about {time} of ${MODES[s.mode]}`,
            },
          },
        });
      }
      for (const spot of route.parking) {
        addMarker(spot.at, "P", {
          filled: true, size: 22,
          extra: {
            attributes: { slope: spot.slope_deg, where: position(spot.at) },
            popupTemplate: {
              title: spot.kind === "board" ? "Rover pickup" : "Rover parking",
              content: (spot.kind === "board" ? "The crew boards the rover here." : "The rover is parked here; the crew goes on from here.") +
                       "<br>Ground slope {slope}°, firm ground<br>{where}",
            },
          },
        });
      }
    }
    if (state.start) addMarker(state.start, "A");
    if (state.end) addMarker(state.end, "B");
  }

  // ---- Results ----
  function card(name, route, r) {
    const { label, color } = ROUTES[name];
    const same = name === "quickest" && route.same_as_safest;
    const hazards = route.hazards.map((h) => `
      <div class="hazard" style="border-color:${LEVEL_COLORS[h.level]}">
        <b>${LEVELS[h.level]}${h.unavoidable ? ", unavoidable" : ""}:</b> ${h.label}, ${length(h.distance_m)} ${h.mode === "drive" ? "driven" : "on foot"}</div>`).join("");
    const leg = (km, minutes) => (km ? `${km.toFixed(1)} km, ${duration(minutes)}` : "none");
    return `
      <div class="card">
        <h4><label><input type="checkbox" data-route="${name}" ${state.shown[name] ? "checked" : ""}>
          <span class="swatch" style="background:${color};color:${color}"></span>${label} route${route.viable ? "" : ` <span style="color:${BAD}">(not viable)</span>`}</label></h4>
        ${same ? `<div class="hint">Same as the safest route: nothing quicker is acceptable.</div>` : `
        ${route.reasons.map((w) => `<div class="bad"><b>Not viable:</b> ${w}</div>`).join("")}
        <div class="total">${duration(route.minutes)}<small>${route.distance_km.toFixed(1)} km, one way</small></div>
        <div class="split" style="color:${color}" title="Share of the distance by rover (solid) and on foot (dotted)">
          ${route.drive_km ? `<i style="flex:${route.drive_km};background:currentColor"></i>` : ""}
          ${route.walk_km ? `<i class="walk" style="flex:${route.walk_km}"></i>` : ""}
        </div>
        <table>
          <tr><td>By rover</td><td>${leg(route.drive_km, route.drive_minutes)}</td></tr>
          <tr><td>On foot</td><td>${leg(route.walk_km, route.walk_minutes)}</td></tr>
          <tr><td style="border:none">Rover range used</td><td style="border:none">${route.range_used_km.toFixed(0)} of ${r.range_km} km</td></tr>
          <tr><td colspan="2" style="padding:0"><div class="meter ${route.range_used_km > r.range_km ? "is-bad" : ""}"><i style="width:${Math.min(100, route.range_used_km / r.range_km * 100).toFixed(0)}%"></i></div></td></tr>
          <tr><td>Climb / descent</td><td>${route.climb_m} m / ${route.descent_m} m</td></tr>
          <tr><td>Steepest ground</td><td>${route.max_slope_deg.toFixed(0)}°</td></tr>
          <tr><td>Coldest ground</td><td>${route.coldest_c} °C</td></tr>
          <tr><td>Radiation dose</td><td>${Math.round(route.dose_usv)} µSv</td></tr>
        </table>
        ${hazards || `<div class="hazard" style="border-color:${color}">No hazards on this route.</div>`}
        ${route.warnings.map((w) => `<div class="warn">${w}</div>`).join("")}`}
      </div>`;
  }

  function show() {
    const pick = (which) => (state[which]
      ? `${state.names[which] ? escapeHtml(state.names[which]) + ": " : ""}${position(state[which])}`
      : `<span class="hint">not set</span>`);
    $("routePoints").innerHTML = `A: ${pick("start")}<br>B: ${pick("end")}`;
    $("routePickA").setAttribute("aria-pressed", state.picking === "start");
    $("routePickB").setAttribute("aria-pressed", state.picking === "end");
    view.container.style.cursor = state.picking ? "crosshair" : "";
    const r = state.result;
    if (r) {
      const clear = r.unavoidable_level === 0;
      $("routeResult").innerHTML = `
        <div class="verdict ${r.viable ? "" : "is-bad"}">${r.viable ? "" : `<b style="color:${BAD}">Not viable.</b> `}${r.viability}</div>
        <div class="verdict" style="margin-top:6px;${clear ? "" : `border-color:${LEVEL_COLORS[r.unavoidable_level]}`}">${r.verdict}</div>
        ${card("safest", r.routes.safest, r)}${card("quickest", r.routes.quickest, r)}`;
    }
    draw();
  }

  // ---- Planning ----
  let request = 0;
  function plan() {
    if (!state.start || !state.end) return Promise.resolve(show());
    const id = ++request;                       // a newer request makes this one's answer stale
    state.result = null;
    $("routeResult").innerHTML = `<div class="hint" style="margin-top:10px">Finding routes… long trips take up to half a minute.</div>`;
    show();
    const query = `from_lon=${state.start[0]}&from_lat=${state.start[1]}&to_lon=${state.end[0]}&to_lat=${state.end[1]}` +
                  `&ls=${state.ls}&local_time=${state.localTime}&range_km=${state.rangeKm}&max_walk_km=${state.maxWalkKm}`;
    return fetch(`/routing/astronaut?${query}`)
      .then((r) => r.json().then((body) => (r.ok ? body : Promise.reject(new Error(body.detail || "Routing failed")))))
      .then((result) => {
        if (id !== request) return;
        state.result = result;
        show();
        view.goTo(layer.graphics.toArray(), { duration: 800 }).catch(() => {});
      })
      .catch((error) => {
        if (id !== request) return;
        $("routeResult").innerHTML = `<div class="bad" style="margin-top:10px">${escapeHtml(error.message)}</div>`;
      });
  }

  // name: what the point was found by, if it was searched for. fly: move the camera to it
  // (when it is the only point; with both set the camera frames the route).
  function setPoint(which, lon, lat, name = "", fly = false) {
    state[which] = [lon, lat];
    state.names[which] = name;
    inputs[which].value = name || position(state[which]);
    state.picking = which === "start" && !state.end && !fly ? "end" : null;   // after picking A on the map, go straight on to B
    if (fly && !(state.start && state.end)) {
      view.goTo({ target: new Graphic({ geometry: { type: "point", x: lon, y: lat, spatialReference: { wkid: MARS_WKID } } }), scale: 1500000 },
                { duration: 800 }).catch(() => {});
    }
    return plan();
  }

  const limit = (id, key) => $(id).addEventListener("change", (e) => {
    const value = parseFloat(e.target.value);
    if (!(value > 0)) { e.target.value = state[key]; return; }
    state[key] = value;
    plan();
  });
  limit("routeRange", "rangeKm");
  limit("routeWalk", "maxWalkKm");

  $("routePickA").addEventListener("click", () => { state.picking = state.picking === "start" ? null : "start"; show(); });
  $("routePickB").addEventListener("click", () => { state.picking = state.picking === "end" ? null : "end"; show(); });
  $("routeSeason").addEventListener("change", (e) => { state.ls = +e.target.value; plan(); });
  $("routeTime").addEventListener("change", (e) => { state.localTime = +e.target.value; plan(); });
  $("routeClear").addEventListener("click", () => {
    request++;
    Object.assign(state, { start: null, end: null, names: { start: "", end: "" }, picking: null, result: null });
    inputs.start.value = inputs.end.value = "";
    $("routeResult").innerHTML = "";
    show();
  });
  panel.addEventListener("change", (e) => {
    const name = e.target.dataset && e.target.dataset.route;
    if (name) { state.shown[name] = e.target.checked; draw(); }
  });
  view.on("click", (event) => {
    const where = state.picking && clickedGroundPoint(event);   // from picking.js
    if (!where) return;
    event.stopPropagation();                    // no popup while picking a point
    setPoint(state.picking, where.longitude, where.latitude);
  });

  show();
  // plan([lon, lat], [lon, lat]) sets both points and resolves when the routes are drawn.
  // search("A" or "B", text) types into a search box and submits it. parseLatLon is the coordinate reader.
  return {
    layer, markers, group, state, parseLatLon, find,
    plan: (start, end) => {
      Object.assign(state, { start, end, names: { start: "", end: "" }, picking: null });
      inputs.start.value = position(start);
      inputs.end.value = position(end);
      return plan();
    },
    search: (letter, text) => {
      const input = $("routeSearch" + letter);
      input.value = text;
      input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
    },
  };
}
