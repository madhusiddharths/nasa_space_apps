// Makes map clicks carry a location again.
//
// With our own terrain layer loaded, the map engine cannot work out where a click lands:
// view.toMap() and event.mapPoint come back empty, so nothing that reads a clicked spot works
// (route start and end, the radiation and temperature readouts). Going the other way still
// works: the view can say where a ground point appears on screen, and what the ground
// elevation is. So this finds the ground point whose screen position is the click, by
// stepping towards it.
//
// index.html calls addGroundPicking(view, { Point }) once. Click handlers then call
// clickedGroundPoint(event), which gives { longitude, latitude } or null (sky, far side),
// in place of reading event.mapPoint.

let clickedGroundPoint = (event) => event.mapPoint || null;   // until addGroundPicking runs

function addGroundPicking(view, { Point }) {
  const M_PER_DEG = Math.PI * 3396190 / 180;      // metres per degree of latitude on Mars
  const RADIUS = 3396190;

  const ground = (lon, lat) => {
    const sampler = view.groundView && view.groundView.elevationSampler;
    const z = sampler ? sampler.elevationAt(lon, lat) : 0;
    return Number.isFinite(z) && Math.abs(z) < 1e6 ? z : 0;   // the sampler's "no data" is a huge number
  };
  const point = (lon, lat) => new Point({ x: lon, y: lat, z: ground(lon, lat), spatialReference: view.spatialReference });
  const screen = (lon, lat) => view.toScreen(point(lon, lat));

  // Lon/lat of the ground under screen position (x, y), or null when it cannot be found
  // (sky, the far side of the planet).
  function groundPoint(x, y) {
    const camera = view.camera;
    const height = Math.max(camera.position.z - ground(camera.position.longitude, camera.position.latitude), 100);
    const cosLat = (lat) => Math.max(Math.cos(lat * Math.PI / 180), 0.01);

    // Start where the camera is looking: straight down, pushed forward by the tilt.
    const ahead = height * Math.tan(Math.min(camera.tilt, 75) * Math.PI / 180) / M_PER_DEG;
    const heading = camera.heading * Math.PI / 180;
    let lat = Math.max(-89, Math.min(89, camera.position.latitude + ahead * Math.cos(heading)));
    let lon = camera.position.longitude + ahead * Math.sin(heading) / cosLat(lat);

    const step = Math.max(height / M_PER_DEG * 0.01, 1e-6);   // about 1% of the camera height
    const reach = Math.max(height / M_PER_DEG, 1e-4) * 2;     // largest move per round
    for (let i = 0; i < 40; i++) {
      const here = screen(lon, lat);
      const east = screen(lon + step / cosLat(lat), lat);
      const north = screen(lon, lat + step);
      if (!here || !east || !north) return null;
      const ex = x - here.x, ey = y - here.y;
      if (Math.hypot(ex, ey) < 0.5) {
        return visible(lon, lat, camera) ? { longitude: wrap(lon), latitude: lat } : null;
      }
      // Screen movement per step east and per step north, then solve for the move that closes the gap.
      const a = east.x - here.x, b = north.x - here.x, c = east.y - here.y, d = north.y - here.y;
      const det = a * d - b * c;
      if (Math.abs(det) < 1e-9) return null;
      let dEast = (ex * d - b * ey) / det * step, dNorth = (a * ey - ex * c) / det * step;
      const size = Math.hypot(dEast, dNorth);
      if (size > reach) { dEast *= reach / size; dNorth *= reach / size; }
      lat = Math.max(-89.9, Math.min(89.9, lat + dNorth));
      lon += dEast / cosLat(lat);
    }
    return null;
  }

  const wrap = (lon) => ((lon + 180) % 360 + 360) % 360 - 180;

  // True when the point is on the side of the planet the camera can see.
  function visible(lon, lat, camera) {
    const rad = Math.PI / 180;
    const p1 = camera.position.latitude * rad, p2 = lat * rad, dl = (lon - camera.position.longitude) * rad;
    const cosAngle = Math.sin(p1) * Math.sin(p2) + Math.cos(p1) * Math.cos(p2) * Math.cos(dl);
    return cosAngle > RADIUS / (RADIUS + Math.max(camera.position.z, 0) + 30000);   // 30 km of slack for mountains
  }

  clickedGroundPoint = (event) => {
    if (event.mapPoint) return { longitude: event.mapPoint.longitude, latitude: event.mapPoint.latitude };
    return groundPoint(event.x, event.y);
  };

  return { groundPoint, elevation: ground };
}
