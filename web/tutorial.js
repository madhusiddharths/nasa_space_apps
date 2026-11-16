// A quick tour of the main controls: five short steps, each with a ring around the part
// of the page it talks about. It runs once, the first time someone opens the app (after
// the loading veil has lifted), and again whenever "Guide" at the foot of the rail is clicked.
//
// index.html calls addTutorial(dock), where dock is what addDock returned (web/layout.js).
// Styled in theme.css.

function addTutorial(dock) {
  const SEEN = "marsTutorialSeen";               // remembered in this browser once the tour has been closed
  // Each step: the part of the page it rings, the dock mode to open first (or none), a
  // title, and the lines of text: [what to do, what it does].
  const STEPS = [
    { target: "#viewDiv", title: "Move around Mars", lines: [
      ["Drag", "move the map"],
      ["Right-drag", "tilt and turn"],
      ["Scroll", "zoom in and out"],
      ["Buttons, bottom right", "zoom, face north, switch between moving and turning"],
    ] },
    { target: "#rail", title: "Pick a mode", lines: [
      ["Route", "plan a trip by rover and on foot"],
      ["Immersive", "stand on the surface and look around"],
      ["Layers, Temp", "what the map shows"],
      ["Places, Tools", "fly to a place, measure, read coordinates"],
      ["Click the open mode again", "close its panel for a wider map"],
    ] },
    { target: "#dock", mode: "route", title: "Plan a route", lines: [
      ["A and B", "type a crater name or coordinates, or press Pick on map and click the ground"],
      ["Range and walking limit", "how far the rover drives and the crew may walk"],
      ["Result", "the safest and the quickest trip, with their hazards"],
    ] },
    { target: "#dock", mode: "layers", title: "Choose what the map shows", lines: [
      ["Eye icon", "switch a layer on or off"],
      ["Data layer", "one coloured map at a time: temperature, radiation, ice, elevation, firmness"],
      ["Contour lines", "can be shown over any of them"],
    ] },
    { target: "#statusBar", title: "Read the ground", lines: [
      ["Move the cursor", "position and elevation under it"],
      ["Click the ground", "the day's ground temperature there, and the radiation dose in Gale crater"],
    ] },
  ];

  const tour = document.createElement("div");      // sits over the map; holds the card
  tour.id = "tour";
  tour.hidden = true;
  tour.innerHTML = `
    <div class="card holo-panel" role="dialog" aria-modal="false" aria-labelledby="tourTitle">
      <div class="count" id="tourCount"></div>
      <h3 id="tourTitle"></h3>
      <table id="tourLines"></table>
      <div class="row">
        <button id="tourSkip">Skip</button>
        <button id="tourBack">Back</button>
        <button id="tourNext"></button>
      </div>
    </div>`;
  const ring = document.createElement("div");      // drawn around the part a step talks about
  ring.id = "tourRing";
  ring.hidden = true;
  document.body.append(tour, ring);
  const $ = (id) => tour.querySelector("#" + id);

  let step = 0, restore;                           // restore: the dock mode that was open before the tour

  function placeRing() {
    const target = document.querySelector(STEPS[step].target);
    const box = target && !target.hidden ? target.getBoundingClientRect() : null;
    ring.hidden = tour.hidden || !box || !box.width;
    if (ring.hidden) return;
    Object.assign(ring.style, { left: `${box.left}px`, top: `${box.top}px`, width: `${box.width}px`, height: `${box.height}px` });
  }

  function show() {
    const { title, lines, mode } = STEPS[step];
    // Open the panel the step is about, unless that mode is locked (the immersive view locks some).
    const button = mode && document.querySelector(`#rail button[data-mode="${mode}"]`);
    if (button && !button.disabled) dock.show(mode);
    $("tourCount").textContent = `Step ${step + 1} of ${STEPS.length}`;
    $("tourTitle").textContent = title;
    $("tourLines").innerHTML = lines.map(([what, does]) => `<tr><td>${what}</td><td>${does}</td></tr>`).join("");
    $("tourBack").disabled = step === 0;
    $("tourNext").textContent = step === STEPS.length - 1 ? "Done" : "Next";
    placeRing();
    $("tourNext").focus();
  }

  function open() {
    restore = document.querySelector("#rail button[data-mode][aria-pressed=true]");
    step = 0;
    tour.hidden = false;
    show();
  }

  function close() {
    tour.hidden = ring.hidden = true;
    try { localStorage.setItem(SEEN, "1"); } catch (e) { /* private window: the tour shows again next time */ }
    // Put back the panel that was open before, where the tour opened another.
    const mode = restore && restore.dataset.mode;
    if (mode && !restore.disabled && STEPS.some((s) => s.mode)) dock.show(mode);
    help.focus();
  }

  const go = (by) => {
    if (step + by >= STEPS.length) return close();
    step = Math.max(0, step + by);
    show();
  };
  $("tourNext").addEventListener("click", () => go(1));
  $("tourBack").addEventListener("click", () => go(-1));
  $("tourSkip").addEventListener("click", close);
  document.addEventListener("keydown", (e) => {
    if (tour.hidden) return;
    if (e.key === "Escape") close();
    else if (e.key === "ArrowRight") go(1);
    else if (e.key === "ArrowLeft") go(-1);
  });
  window.addEventListener("resize", placeRing);

  // "Guide" at the foot of the rail starts the tour again. It is not a mode: it has no panel.
  const help = document.createElement("button");
  help.className = "help";
  help.title = "Show the quick guide to the controls";
  help.innerHTML = `<span class="esri-icon-question" aria-hidden="true"></span>Guide`;
  help.addEventListener("click", open);
  document.getElementById("rail").appendChild(help);

  // First visit: start once the loading veil has gone, so the tour does not sit on top of it.
  let seen = false;
  try { seen = !!localStorage.getItem(SEEN); } catch (e) { /* no storage: show it */ }
  if (!seen) {
    const wait = setInterval(() => {
      if (document.getElementById("mapVeil")) return;
      clearInterval(wait);
      open();
    }, 300);
  }

  return { open, close };
}
