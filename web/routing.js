// Astronaut route planner: set A and B, get the safest and the quickest trip by rover and on foot.
// A and B are set by searching (a place name, a CTX grid tile, or coordinates in any of the
// coordinate widget's formats) or by picking them on the map.
// The routes come from server.py (/routing/astronaut), which runs routing.py.
// index.html calls addRouting(map, view, { GraphicsLayer, Graphic, Expand, coordinateFormatter, selectedFormat }).

function addRouting(map, view, { GraphicsLayer, Graphic, Expand, coordinateFormatter, selectedFormat }) {
  const MARS_WKID = 104971;
  const ROUTES = {
    safest: { label: "Safest", color: "#00e676" },
    quickest: { label: "Quickest", color: "#40a9ff" },
  };
  // Hazard levels as routing.py numbers them: 0 Clear, 1 Caution, 2 Danger, 3 Extreme.
  const LEVELS = ["Clear", "Caution", "Danger", "Extreme"];
  const LEVEL_COLORS = [null, "#ffc400", "#ff3d00", "#d500f9"];
  const BAD = "#ff6e6e";
  const SEASONS = [[0, "Northern spring"], [90, "Northern summer"], [180, "Northern autumn"], [270, "Northern winter"]];
  const MODES = { drive: "driving", walk: "walking" };

  const state = {
    start: null, end: null, names: { start: "", end: "" }, picking: null,
    ls: 90, localTime: 12, rangeKm: 125, maxWalkKm: 10,       // the last two are replaced by routing.py's defaults
    shown: { safest: true, quickest: true }, result: null,
  };

  const layer = new GraphicsLayer({ title: "Astronaut Route", elevationInfo: { mode: "on-the-ground" } });
  map.add(layer);

  // ---- Panel ----
  const style = document.createElement("style");
  style.textContent = `
    #routePanel { width: 320px; padding: 12px; font-size: 13px; line-height: 1.4; max-height: max(220px, calc(100vh - 380px)); overflow-y: auto; box-sizing: border-box; }
    #routePanel h3 { margin: 0 0 8px; font-size: 15px; font-weight: 600; }
    #routePanel button { padding: 5px 8px; border: 1px solid #555; background: none; color: inherit; cursor: pointer; border-radius: 3px; font: inherit; }
    #routePanel button[aria-pressed=true] { background: #d1d1d1; color: #242424; border-color: #d1d1d1; }
    #routePanel .row { display: flex; gap: 6px; margin-top: 8px; }
    #routePanel .row > * { flex: 1; min-width: 0; }
    #routePanel select, #routePanel input[type=text], #routePanel input[type=number] {
      width: 100%; box-sizing: border-box; background: #242424; color: inherit; border: 1px solid #555; border-radius: 3px; padding: 4px 6px; font: inherit; }
    #routePanel .place { display: flex; gap: 6px; align-items: center; margin-top: 6px; }
    #routePanel .place b { width: 12px; }
    #routePanel .place input { flex: 1; min-width: 0; }
    #routePanel .place button { flex: none; }
    #routePanel .suggest { margin: 2px 0 0 18px; border: 1px solid #555; border-radius: 3px; }
    #routePanel .suggest div { padding: 3px 6px; cursor: pointer; }
    #routePanel .suggest div[aria-selected=true], #routePanel .suggest div:hover { background: #3a3a3a; }
    #routePanel .suggest small { opacity: 0.7; margin-left: 6px; }
    #routePanel label.field { display: block; font-size: 11px; opacity: 0.9; }
    #routePanel .points { margin-top: 6px; font-variant-numeric: tabular-nums; }
    #routePanel .hint { opacity: 0.7; }
    #routePanel .verdict { margin-top: 12px; padding: 8px; border-left: 3px solid #00e676; background: rgba(255, 255, 255, 0.06); }
    #routePanel .card { margin-top: 12px; padding-top: 10px; border-top: 1px solid #444; }
    #routePanel .card h4 { margin: 0 0 4px; font-size: 14px; font-weight: 600; }
    #routePanel .card h4 label { cursor: pointer; }
    #routePanel .swatch { display: inline-block; width: 18px; height: 4px; vertical-align: middle; margin-right: 6px; }
    #routePanel table { width: 100%; border-collapse: collapse; }
    #routePanel td { padding: 1px 0; }
    #routePanel td:last-child { text-align: right; font-variant-numeric: tabular-nums; }
    #routePanel .hazard { margin-top: 4px; padding-left: 8px; border-left: 3px solid; }
    #routePanel .hazard b { font-weight: 600; }
    #routePanel .warn { margin-top: 4px; color: #ffc400; }
    #routePanel .bad { margin-top: 4px; color: ${BAD}; }
    #routePanel .note { margin-top: 12px; font-size: 11px; opacity: 0.7; }
  `;
  document.head.appendChild(style);

  const placeRow = (letter, which, what) => `
    <div class="place">
      <b>${letter}</b>
      <input type="text" id="routeSearch${letter}" data-which="${which}" autocomplete="off" spellcheck="false"
             placeholder="Place, grid tile or coordinates" aria-label="${what}: search by place name, grid tile or coordinates">
      <button id="routePick${letter}" title="Then click the map where the trip ${which === "start" ? "starts" : "ends"}">Pick on map</button>
    </div>
    <div class="suggest" id="routeSuggest${letter}" hidden></div>`;

  const panel = document.createElement("div");
  panel.id = "routePanel";
  panel.className = "esri-widget esri-widget--panel";
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
  view.ui.add(new Expand({ view, content: panel, expandIconClass: "esri-icon-directions",
                           expandTooltip: "Astronaut route", expanded: false, group: "top-left" }), "top-left");

  const $ = (id) => panel.querySelector("#" + id);
  $("routeSeason").value = state.ls;
  $("routeTime").value = state.localTime;
  $("routeRange").value = state.rangeKm;
  $("routeWalk").value = state.maxWalkKm;

  const note = (n) => {
    $("routeNote").innerHTML = `
      Solid line: by rover. Dotted line: on foot. P: where the rover is boarded or parked
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
  const addPoint = (p, letter, color = "white", extra = {}) => {
    const geometry = { type: "point", x: p[0], y: p[1], spatialReference: { wkid: MARS_WKID } };
    layer.add(new Graphic({ geometry, symbol: { type: "simple-marker", color, size: 20, outline: { color: "black", width: 1.5 } }, ...extra }));
    layer.add(new Graphic({ geometry, symbol: { type: "text", text: letter, color: "black", yoffset: -4.5, font: { size: 11, weight: "bold" } } }));
  };

  function draw() {
    layer.removeAll();
    const routes = state.result ? state.result.routes : {};
    // Quickest first, so the safest line stays on top where the two share ground.
    for (const name of ["quickest", "safest"]) {
      const route = routes[name];
      if (!route || !state.shown[name] || (name === "quickest" && route.same_as_safest && state.shown.safest)) continue;
      addLine(route.line, "black", 7);
      addLine(route.line, ROUTES[name].color, 4);
      for (const leg of route.legs) {            // walked legs get a dotted black core
        if (leg.mode === "walk") addLine(route.line.slice(leg.from, leg.to + 1), "black", 2, {}, "short-dot");
      }
      for (const s of route.stretches) {
        const part = route.line.slice(s.from, s.to + 1);
        if (s.unavoidable) addLine(part, "white", 11);
        addLine(part, LEVEL_COLORS[s.level], s.unavoidable ? 7 : 4, {
          attributes: { hazards: s.hazards.join("; "), length: length(s.distance_m), time: duration(Math.round(s.minutes)) },
          popupTemplate: {
            title: `${LEVELS[s.level]}${s.unavoidable ? ", unavoidable" : ""} (${ROUTES[name].label.toLowerCase()} route)`,
            content: `{hazards}<br>{length}, about {time} of ${MODES[s.mode]}`,
          },
        });
      }
      for (const spot of route.parking) {
        addPoint(spot.at, "P", "#8ec5ff", {
          attributes: { slope: spot.slope_deg, where: position(spot.at) },
          popupTemplate: {
            title: spot.kind === "board" ? "Rover pickup" : "Rover parking",
            content: (spot.kind === "board" ? "The crew boards the rover here." : "The rover is parked here; the crew goes on from here.") +
                     "<br>Ground slope {slope}°, firm ground<br>{where}",
          },
        });
      }
    }
    if (state.start) addPoint(state.start, "A");
    if (state.end) addPoint(state.end, "B");
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
          <span class="swatch" style="background:${color}"></span>${label} route${route.viable ? "" : ` <span style="color:${BAD}">(not viable)</span>`}</label></h4>
        ${same ? `<div class="hint">Same as the safest route: nothing quicker is acceptable.</div>` : `
        ${route.reasons.map((w) => `<div class="bad"><b>Not viable:</b> ${w}</div>`).join("")}
        <table>
          <tr><td>Total time</td><td>${duration(route.minutes)}</td></tr>
          <tr><td>Distance</td><td>${route.distance_km.toFixed(1)} km</td></tr>
          <tr><td>By rover</td><td>${leg(route.drive_km, route.drive_minutes)}</td></tr>
          <tr><td>On foot</td><td>${leg(route.walk_km, route.walk_minutes)}</td></tr>
          <tr><td>Rover range used</td><td>${route.range_used_km.toFixed(0)} of ${r.range_km} km</td></tr>
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
        <div class="verdict" style="border-color:${r.viable ? ROUTES.safest.color : BAD}">${r.viable ? "" : `<b style="color:${BAD}">Not viable.</b> `}${r.viability}</div>
        <div class="verdict" style="margin-top:6px;border-color:${clear ? ROUTES.safest.color : LEVEL_COLORS[r.unavoidable_level]}">${r.verdict}</div>
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
    layer, state, parseLatLon,
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
