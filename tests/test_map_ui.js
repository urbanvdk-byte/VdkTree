/* v1.1.1 — frontend structure and security contract. */
"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const html=fs.readFileSync("index.html","utf8");
const js=fs.readFileSync("ui/map.js","utf8");
const css=fs.readFileSync("ui/style.css","utf8");
for(const token of ["v1.1.1", "ui/map.js", "ui/style.css","auth/client.js","id=\"objectForm\"","id=\"details\"","id=\"addAreaButton\"","id=\"filter\""])
  assert.ok(html.includes(token), "Missing HTML component: "+token);
assert.ok(html.includes("ui/management.js"),"Management screens must be included");
assert.ok(html.includes('href="./registry.html?v=1.1.1"'),"Registry navigation must bust cached HTML");
assert.ok(html.includes('src="./ui/map.js?v=1.1.1"'),"Map must load current JavaScript, not cached v1.1.0");
assert.ok(html.includes('href="./ui/style.css?v=1.1.1"'),"Map must load current style");
assert.ok(js.includes('L.control.zoom({position:"bottomleft"}).addTo(map)'),"Zoom must not hide below top filters");
assert.ok(js.includes('zoomControl:false'),"Default top-left zoom must be disabled");
assert.ok(css.includes(".leaflet-bottom.leaflet-left .leaflet-control-zoom"),"Zoom position styling missing");
assert.ok(js.includes('const legacyKey = "vdktree-demo-v020"'),"Legacy local demo migration missing");
assert.ok(js.includes('vdktree-local-demo-archive-v111'),"Legacy data must be archived, not lost");
assert.ok(js.includes('localStorage.removeItem(legacyKey)'),"Old key must be retired after backup");
assert.ok(!js.includes('Локальная демозапись'),"Legacy demo markers must never be rendered");
const adminJs=fs.readFileSync("ui/management.js","utf8");
for(const token of ["openUsers","usersDialog","/api/v2/admin/users","revoke-sessions","reset-credentials","isAdmin()"]) assert.ok(adminJs.includes(token),"Users admin UI missing: "+token);
assert.ok(js.includes("map.attributionControl.setPrefix(false)"),"Leaflet logo prefix must stay hidden");
assert.ok(js.includes("© OpenStreetMap contributors"),"OpenStreetMap credit must remain");
for(const token of ["vdk-marker","vdk-alert","shrub","confirmed","proposed","needs_clarification","vdk-auth-btn",
   "/api/v2/objects","/notes","/confirm","editable(","604800"])
  assert.ok(js.includes(token), "Expected map behavior missing: "+token);
assert.ok(css.includes(".vdk-marker.shrub"),"Missing blue shrub marker styles");
assert.ok(css.includes(".vdk-marker.tree.confirmed"),"Missing confirmed green tree styles");
assert.ok(css.includes(".vdk-marker.tree.proposed"),"Missing proposed grey tree styles");
assert.ok(!/innerHTML\s*=\s*.*\bo\.comment\b/.test(js),"Never insert raw user comments");
console.log("Frontend v1.1.1 static contract checks passed");
