// Immersive view: stand on the surface and look around, the way a street-level view works.
//
// Opening "Immersive" in the rail turns the mode on. While it is on, only the CTX imagery
// is shown and the other modes in the rail are locked, except Places:
//   choosing   the globe is zoomed all the way out; the visitor turns it, zooms in (or flies
//              to a place with Places) and clicks the spot to stand on
//   standing   the camera is just above the ground there; dragging turns the head, and the
//              six buttons at the bottom of the view move it: forward, back, left, right,
//              up, down. Nothing else moves the camera.
// "Exit immersive view" in the panel puts the layers, the rail and the camera back.
//
// index.html calls addImmersive(map, view, { Camera, container, picking, imagery, closeDock });
// picking is what addGroundPicking returned, imagery is the CTX layer, closeDock() closes the dock.
// The panel and the movement buttons are styled in theme.css.

function addImmersive(map, view, { Camera, container, picking, imagery, closeDock }) {
  const M_PER_DEG = Math.PI * 3396190 / 180;       // metres per degree of latitude on Mars
  // The daytime sky seen from the ground: dust in the air makes it butterscotch, not blue
  // (Viking, Pathfinder and rover panoramas). Part of the scene, not of the interface.
  const MARS_SKY = [201, 160, 122, 1];
  const CLIMB_M_S = 50;                            // up and down, while a button is held
  // Forward, back, left and right: faster the higher the camera is, so the ground passes at
  // a similar pace at any height. Steeper than in proportion to the height, well short of
  // exponential: 150 m/s at the ground, about 300 at 500 m, 950 at 2 km, 6 km/s at 10 km.
  const groundSpeed = (height) => 150 + 0.06 * height ** 1.25;
  const HEIGHT_M = [5, 10000];                     // above the ground; the map engine holds its camera 5 m up
  const GLOBE_HEIGHT_M = 14000000;                 // camera height that shows the whole planet
  const OPEN_MODES = ["immersive", "places"];      // rail modes that stay usable while the mode is on
  // The six movement buttons: [key, label, title, metres ahead, to the right, up] per metre moved.
  const MOVES = [
    ["up", "Up", "Rise", 0, 0, 1], ["forward", "↑", "Move forward", 1, 0, 0], null,
    ["left", "←", "Move left", 0, -1, 0], null, ["right", "→", "Move right", 0, 1, 0],
    ["down", "Down", "Sink", 0, 0, -1], ["back", "↓", "Move back", -1, 0, 0], null,
  ];

  const state = { phase: "off", lon: 0, lat: 0, height: HEIGHT_M[0], heading: 0, tilt: 88, fov: 70 };
  let saved = null, sky = null, frame = 0, before = 0, shown = "";
  const held = new Set();                          // movement buttons being held

  // ---- Panel ----
  const panel = document.createElement("div");
  panel.id = "immersivePanel";
  panel.className = "esri-widget dock-panel";
  panel.innerHTML = `
    <h3>Immersive view</h3>
    <div class="hint" id="immHint"></div>
    <table id="immLive">
      ${["Standing at", "Ground elevation", "Height above ground", "Looking"].map((label) => `<tr><td>${label}</td><td>–</td></tr>`).join("")}
    </table>
    <div class="row"><button id="immAgain">Choose another place</button></div>
    <div class="row"><button id="immExit">Exit immersive view</button></div>
    <div class="note">While immersive view is on, only the imagery is shown and the other modes are locked,
      except Places.<br><br>
      The imagery is 5 m per pixel on 200 m terrain, so the ground at your feet is soft; crater walls,
      mountains and the horizon are what this view shows well. Rise for a sharper ground.</div>
  `;
  container.appendChild(panel);
  const $ = (id) => panel.querySelector("#" + id);
  const COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];

  // ---- Movement buttons, on the map ----
  const pad = document.createElement("div");
  pad.id = "immersivePad";
  pad.className = "holo-panel";
  pad.setAttribute("aria-label", "Move");
  pad.innerHTML = MOVES.map((m) => (m ? `<button data-move="${m[0]}" title="${m[2]} (hold)" aria-label="${m[2]}">${m[1]}</button>` : "<span></span>")).join("");
  view.ui.add(pad, "bottom-right");

  function show() {
    const standing = state.phase === "standing";
    $("immHint").textContent = standing
      ? "Drag to look around, scroll to zoom. Move with the six buttons at the bottom of the view: hold one to keep moving."
      : "Turn Mars around, zoom in, and click the place where you want to stand. Or open Places to search for a place or fly to a landmark, then click the spot.";
    $("immLive").hidden = $("immAgain").parentElement.hidden = pad.hidden = !standing;
    view.container.style.cursor = state.phase === "choosing" ? "crosshair" : "";
    view.container.classList.toggle("is-standing", standing);     // hides the map's own zoom and compass (theme.css)
    for (const button of document.querySelectorAll("#rail button[data-mode]")) {
      button.disabled = state.phase !== "off" && !OPEN_MODES.includes(button.dataset.mode);
    }
  }

  // Puts the camera where the state says. The ground height is read again every time: it
  // sharpens as the terrain under the camera loads.
  function apply() {
    const ground = picking.elevation(state.lon, state.lat);
    const heading = (state.heading % 360 + 360) % 360;
    const now = [state.lon, state.lat, ground, state.height, heading, state.tilt, state.fov].map((v) => v.toFixed(7)).join();
    if (now === shown) return;
    shown = now;
    view.camera = new Camera({
      position: { x: state.lon, y: state.lat, z: ground + state.height, spatialReference: view.spatialReference },
      heading, tilt: state.tilt, fov: state.fov,
    });
    const metres = (m) => `${Math.round(m).toLocaleString("en-US").replace(/,/g, " ").replace("-", "−")} m`;
    const live = [formatPosition(state.lon, state.lat),                               // from layout.js
      metres(ground), metres(state.height), `${COMPASS[Math.round(heading / 45) % 8]}, ${Math.round(heading)}°`];
    panel.querySelectorAll("#immLive td:last-child").forEach((cell, i) => { cell.textContent = live[i]; });
  }

  function tick(now) {
    if (state.phase !== "standing") return;
    // Something else moved the camera (a place chosen in Places): back to choosing a spot.
    const p = view.camera.position;
    if (shown && (Math.abs(p.longitude - state.lon) > 1e-5 || Math.abs(p.latitude - state.lat) > 1e-5)) {
      leaveGround();
      return show();
    }
    const dt = Math.min((now - before) / 1000, 0.1), step = groundSpeed(state.height) * dt;
    before = now;
    const h = state.heading * Math.PI / 180;
    for (const [, , , ahead, right, up] of MOVES.filter((m) => m && held.has(m[0]))) {
      state.lat = Math.max(-89.9, Math.min(89.9, state.lat + step * (ahead * Math.cos(h) - right * Math.sin(h)) / M_PER_DEG));
      const lon = state.lon + step * (ahead * Math.sin(h) + right * Math.cos(h)) / (M_PER_DEG * Math.cos(state.lat * Math.PI / 180));
      state.lon = ((lon + 180) % 360 + 360) % 360 - 180;
      state.height = Math.max(HEIGHT_M[0], Math.min(HEIGHT_M[1], state.height + CLIMB_M_S * dt * up));
    }
    apply();
    frame = requestAnimationFrame(tick);
  }

  // The whole planet in view, over the place the camera is at now.
  function zoomOut() {
    const p = view.camera.position;
    view.goTo(new Camera({
      position: { x: p.longitude, y: p.latitude, z: GLOBE_HEIGHT_M, spatialReference: view.spatialReference }, heading: 0, tilt: 0,
    }), { duration: 1500 }).catch(() => {});
  }

  function start() {
    saved = { camera: view.camera.clone(), layers: map.layers.toArray().map((layer) => [layer, layer.visible]) };
    map.layers.forEach((layer) => { layer.visible = layer === imagery; });    // the imagery only
    view.popup.close();
    state.phase = "choosing";
    show();
    zoomOut();
  }

  function land(lon, lat) {
    const env = view.environment;
    sky = { background: env.background, starsEnabled: env.starsEnabled, atmosphereEnabled: env.atmosphereEnabled };
    Object.assign(env, { background: { type: "color", color: MARS_SKY }, starsEnabled: false, atmosphereEnabled: false });
    view.constraints.tilt.max = 179;               // lets the camera look up past the horizon
    // Draw the ground from 1 m in front of the camera (the map's own setting cuts away the
    // ground at the viewer's feet) out to the far mountains.
    Object.assign(view.constraints.clipDistance, { near: 1, far: 2000000 });
    Object.assign(state, { phase: "standing", lon, lat, height: HEIGHT_M[0], heading: view.camera.heading, tilt: 88, fov: 70 });
    shown = "";
    show();
    before = performance.now();
    frame = requestAnimationFrame(tick);
  }

  function leaveGround() {
    cancelAnimationFrame(frame);
    held.clear();
    Object.assign(view.environment, sky);
    view.constraints.tilt.mode = "auto";
    view.constraints.clipDistance.mode = "auto";
    state.phase = "choosing";
  }

  function exit() {
    if (state.phase === "off") return;
    if (state.phase === "standing") leaveGround();
    state.phase = "off";
    saved.layers.forEach(([layer, visible]) => { layer.visible = visible; });
    view.goTo(saved.camera, { duration: 800 }).catch(() => {});
    show();
    closeDock();
  }

  // Opening the mode in the rail turns it on.
  document.getElementById("rail").addEventListener("click", (e) => {
    if (state.phase === "off" && e.target.closest('button[data-mode="immersive"]')) start();
  });
  $("immAgain").addEventListener("click", () => { leaveGround(); show(); zoomOut(); });
  $("immExit").addEventListener("click", exit);

  // Choosing: a click on the ground is the place to stand.
  view.on("click", (event) => {
    if (state.phase === "off") return;
    event.stopPropagation();
    const where = state.phase === "choosing" && clickedGroundPoint(event);    // from picking.js
    if (where) land(where.longitude, where.latitude);
  });

  // Standing: the map's own navigation is held off. Dragging turns the head, the wheel zooms.
  const standing = (handler) => (event) => {
    if (state.phase !== "standing") return;
    event.stopPropagation();
    handler(event);
  };
  let grab = null;
  view.on("drag", standing((event) => {
    if (event.action === "start") grab = { x: event.x, y: event.y, heading: state.heading, tilt: state.tilt };
    if (!grab) return;
    // The scene follows the pointer: dragging right turns the head left, dragging down looks up.
    state.heading = grab.heading - (event.x - grab.x) * 0.12 * state.fov / 70;
    state.tilt = Math.max(20, Math.min(160, grab.tilt + (event.y - grab.y) * 0.12 * state.fov / 70));
    if (event.action === "end") grab = null;
  }));
  view.on("mouse-wheel", standing((event) => { state.fov = Math.max(15, Math.min(100, state.fov + event.deltaY * 0.03)); }));
  view.on("double-click", standing(() => {}));
  view.on("key-down", standing(() => {}));

  // A movement button moves the camera for as long as it is held.
  pad.addEventListener("pointerdown", (e) => {
    const button = e.target.closest("[data-move]");
    if (!button) return;
    held.add(button.dataset.move);
    button.setPointerCapture(e.pointerId);         // so letting go off the button still ends the move
  });
  for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) {
    pad.addEventListener(type, (e) => { const button = e.target.closest("[data-move]"); if (button) held.delete(button.dataset.move); });
  }

  show();
  return { state, exit };
}
