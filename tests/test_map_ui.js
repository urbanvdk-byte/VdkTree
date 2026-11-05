/* v0.6.0 — frontend structure and security contract. */
"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const html=fs.readFileSync("index.html","utf8");
const js=fs.readFileSync("ui/map.js","utf8");
const css=fs.readFileSync("ui/style.css","utf8");
for(const token of ["v0.6.0", "ui/map.js", "ui/style.css","auth/client.js","id=\"objectForm\"","id=\"details\"","id=\"addAreaButton\"","id=\"filter\""])
  assert.ok(html.includes(token), "Missing HTML component: "+token);
assert.ok(js.includes("map.attributionControl.setPrefix(false)"),"Leaflet logo prefix must stay hidden");
assert.ok(js.includes("© OpenStreetMap contributors"),"OpenStreetMap credit must remain");
for(const token of ["vdk-marker","vdk-alert","shrub","confirmed","proposed","needs_clarification","vdk-auth-btn",
   "/api/v2/objects","/notes","/confirm","editable(","604800","localStorage.getItem"])
  assert.ok(js.includes(token), "Expected map behavior missing: "+token);
assert.ok(css.includes(".vdk-marker.shrub"),"Missing blue shrub marker styles");
assert.ok(css.includes(".vdk-marker.tree.confirmed"),"Missing confirmed green tree styles");
assert.ok(css.includes(".vdk-marker.tree.proposed"),"Missing proposed grey tree styles");
assert.ok(!/innerHTML\s*=\s*.*\bo\.comment\b/.test(js),"Never insert raw user comments");
console.log("Frontend v0.6.0 static contract checks passed");
