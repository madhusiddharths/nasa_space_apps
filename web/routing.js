// Astronaut route planner: pick A and B on the map, get the safest and the quickest walk.
// The routes come from server.py (/routing/astronaut), which runs routing.py.
// index.html calls addRouting(map, view, { GraphicsLayer, Graphic, Expand }).

function addRouting(map, view, { GraphicsLayer, Graphic, Expand }) {
  const MARS_WKID = 104971;
  const ROUTES = {
    safest: { label: "Safest", color: "#00e676" },
    quickest: { label: "Quickest", color: "#40a9ff" },
  };
  // Hazard levels as routing.py numbers them: 0 Clear, 1 Caution, 2 Danger, 3 Extreme.
  const LEVELS = ["Clear", "Caution", "Danger", "Extreme"];
  const LEVEL_COLORS = [null, "#ffc400", "#ff3d00", "#d500f9"];
  const SEASONS = [[0, "Northern spring"], [90, "Northern summer"], [180, "Northern autumn"], [270, "Northern winter"]];

  const state = { start: null, end: null, picking: null, ls: 90, localTime: 12, shown: { safest: true, quickest: true }, result: null };

  const layer = new GraphicsLayer({ title: "Astronaut Route", elevationInfo: { mode: "on-the-ground" } });
  map.add(layer);

  // ---- Panel ----
  const style = document.createElement("style");
  style.textContent = `
    #routePanel { width: 300px; padding: 12px; font-size: 13px; line-height: 1.4; max-height: max(220px, calc(100vh - 380px)); overflow-y: auto; box-sizing: border-box; }
    #routePanel h3 { margin: 0 0 8px; font-size: 15px; font-weight: 600; }
    #routePanel button { padding: 5px 8px; border: 1px solid #555; background: none; color: inherit; cursor: pointer; border-radius: 3px; font: inherit; }
    #routePanel button[aria-pressed=true] { background: #d1d1d1; color: #242424; border-color: #d1d1d1; }
    #routePanel .row { display: flex; gap: 6px; margin-top: 8px; }
    #routePanel .row > * { flex: 1; min-width: 0; }
    #routePanel select { width: 100%; background: #242424; color: inherit; border: 1px solid #555; border-radius: 3px; padding: 4px; font: inherit; }
    #routePanel .points { margin-top: 8px; font-variant-numeric: tabular-nums; }
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
    #routePanel .note { margin-top: 12px; font-size: 11px; opacity: 0.7; }
  `;
  document.head.appendChild(style);

  const panel = document.createElement("div");
  panel.id = "routePanel";
  panel.className = "esri-widget esri-widget--panel";
  panel.innerHTML = `
    <h3>Astronaut route</h3>
    <div class="row">
      <button id="routePickA" title="Then click the map where the walk starts">Set start A</button>
      <button id="routePickB" title="Then click the map where the walk ends">Set destination B</button>
    </div>
    <div class="points" id="routePoints"></div>
    <div class="row">
      <select id="routeSeason" aria-label="Season">
        ${SEASONS.map(([ls, name]) => `<option value="${ls}">${name}</option>`).join("")}
      </select>
      <select id="routeTime" aria-label="Departure, local solar time">
        ${Array.from({ length: 24 }, (_, h) => `<option value="${h}">Leave ${String(h).padStart(2, "0")}:00</option>`).join("")}
      </select>
    </div>
    <div id="routeResult"><div class="hint" style="margin-top:10px">Set a start and a destination up to 100 km apart.
      The map then shows the safest walk and the quickest walk between them.</div></div>
    <div class="row"><button id="routeClear">Clear route</button></div>
    <div class="note">
      Hazards on the lines: <span style="color:${LEVEL_COLORS[1]}">Caution</span>,
      <span style="color:${LEVEL_COLORS[2]}">Danger</span>, <span style="color:${LEVEL_COLORS[3]}">Extreme</span>;
      thick with a white edge where no route can avoid them.
      Walking at 3 km/h on flat firm ground. Terrain is seen at 200 m, ground firmness and temperature at 3 km.
      Planning numbers chosen by the team, not NASA limits.
    </div>
  `;
  view.ui.add(new Expand({ view, content: panel, expandIconClass: "esri-icon-directions",
                           expandTooltip: "Astronaut route", expanded: false, group: "top-left" }), "top-left");

  const $ = (id) => panel.querySelector("#" + id);
  $("routeSeason").value = state.ls;
  $("routeTime").value = state.localTime;

  // ---- Helpers ----
  const duration = (minutes) => (minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")} min`);
  const length = (m) => (m < 1000 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1)} km`);
  const position = (p) => `${Math.abs(p[1]).toFixed(3)}°${p[1] < 0 ? "S" : "N"}, ${p[0].toFixed(3)}°E`;

  // ---- Drawing ----
  const polyline = (line) => ({ type: "polyline", paths: [line], spatialReference: { wkid: MARS_WKID } });
  const stroke = (color, width) => ({ type: "simple-line", color, width, cap: "round", join: "round" });
  const addLine = (line, color, width, extra = {}) => layer.add(new Graphic({ geometry: polyline(line), symbol: stroke(color, width), ...extra }));
  const addPoint = (p, letter) => {
    const geometry = { type: "point", x: p[0], y: p[1], spatialReference: { wkid: MARS_WKID } };
    layer.add(new Graphic({ geometry, symbol: { type: "simple-marker", color: "white", size: 20, outline: { color: "black", width: 1.5 } } }));
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
      for (const s of route.stretches) {
        const part = route.line.slice(s.from, s.to + 1);
        if (s.unavoidable) addLine(part, "white", 11);
        addLine(part, LEVEL_COLORS[s.level], s.unavoidable ? 7 : 4, {
          attributes: { hazards: s.hazards.join("; "), length: length(s.distance_m), time: duration(Math.round(s.minutes)) },
          popupTemplate: {
            title: `${LEVELS[s.level]}${s.unavoidable ? ", unavoidable" : ""} (${ROUTES[name].label.toLowerCase()} route)`,
            content: "{hazards}<br>{length}, about {time} of walking",
          },
        });
      }
    }
    if (state.start) addPoint(state.start, "A");
    if (state.end) addPoint(state.end, "B");
  }

  // ---- Results ----
  function card(name, route) {
    const { label, color } = ROUTES[name];
    const same = name === "quickest" && route.same_as_safest;
    const hazards = route.hazards.map((h) => `
      <div class="hazard" style="border-color:${LEVEL_COLORS[h.level]}">
        <b>${LEVELS[h.level]}${h.unavoidable ? ", unavoidable" : ""}:</b> ${h.label}, ${length(h.distance_m)}</div>`).join("");
    return `
      <div class="card">
        <h4><label><input type="checkbox" data-route="${name}" ${state.shown[name] ? "checked" : ""}>
          <span class="swatch" style="background:${color}"></span>${label} route</label></h4>
        ${same ? `<div class="hint">Same as the safest route: nothing quicker stays off Danger ground.</div>` : `
        <table>
          <tr><td>Distance</td><td>${route.distance_km.toFixed(1)} km</td></tr>
          <tr><td>Walking time</td><td>${duration(route.minutes)}</td></tr>
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
    const pick = (which) => (state[which] ? position(state[which]) : `<span class="hint">not set</span>`);
    $("routePoints").innerHTML = `A: ${pick("start")}<br>B: ${pick("end")}`;
    $("routePickA").setAttribute("aria-pressed", state.picking === "start");
    $("routePickB").setAttribute("aria-pressed", state.picking === "end");
    view.container.style.cursor = state.picking ? "crosshair" : "";
    const r = state.result;
    if (r) {
      const clear = r.unavoidable_level === 0;
      $("routeResult").innerHTML = `
        <div class="verdict" style="border-color:${clear ? ROUTES.safest.color : LEVEL_COLORS[r.unavoidable_level]}">${r.verdict}</div>
        ${card("safest", r.routes.safest)}${card("quickest", r.routes.quickest)}`;
    }
    draw();
  }

  // ---- Planning ----
  let request = 0;
  function plan() {
    if (!state.start || !state.end) return Promise.resolve(show());
    const id = ++request;                       // a newer request makes this one's answer stale
    state.result = null;
    $("routeResult").innerHTML = `<div class="hint" style="margin-top:10px">Finding routes…</div>`;
    show();
    const query = `from_lon=${state.start[0]}&from_lat=${state.start[1]}&to_lon=${state.end[0]}&to_lat=${state.end[1]}` +
                  `&ls=${state.ls}&local_time=${state.localTime}`;
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
        $("routeResult").innerHTML = `<div class="warn" style="margin-top:10px">${error.message}</div>`;
      });
  }

  function setPoint(which, lon, lat) {
    state[which] = [lon, lat];
    state.picking = which === "start" && !state.end ? "end" : null;   // after A, go straight on to B
    return plan();
  }

  $("routePickA").addEventListener("click", () => { state.picking = state.picking === "start" ? null : "start"; show(); });
  $("routePickB").addEventListener("click", () => { state.picking = state.picking === "end" ? null : "end"; show(); });
  $("routeSeason").addEventListener("change", (e) => { state.ls = +e.target.value; plan(); });
  $("routeTime").addEventListener("change", (e) => { state.localTime = +e.target.value; plan(); });
  $("routeClear").addEventListener("click", () => {
    request++;
    Object.assign(state, { start: null, end: null, picking: null, result: null });
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
  return { layer, state, plan: (start, end) => { Object.assign(state, { start, end, picking: null }); return plan(); } };
}
