/* VdkTree v1.1.0 — registry page and public spreadsheet export contract. */
"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const html=fs.readFileSync("registry.html","utf8");
const js=fs.readFileSync("ui/registry.js","utf8");
const css=fs.readFileSync("ui/registry.css","utf8");
const map=fs.readFileSync("ui/map.js","utf8");
const homepage=fs.readFileSync("index.html","utf8");
for(const token of ["v1.1.0","registrySearch","filterGroups","registrySort",
  "columnControls","registryTable","registryRows","treeDetail","detailBody",
  "prevPage","nextPage","activeFilters","closeFilters","auth/client.js"]) {
 assert.ok(html.includes(token),"Registry HTML missing: "+token);
}
for(const token of ["/api/v2/registry","/facets","/meta","/sheet.xlsx",
 "Редактировать профессиональные","Редактировать основные",
 "/expert","/inventory-number","/api/v2/objects/","admin()",
 "sanitary_condition_score","slope_protection","endemic_or_relict"]) {
 assert.ok(js.includes(token),"Registry JavaScript missing: "+token);
}
assert.ok(js.includes("td.textContent"),"User-supplied data must be HTML-escaped by text nodes");
assert.ok(!js.includes("innerHTML="),"No raw user values in innerHTML in registry");
assert.ok(css.includes(".registry-filters")&&css.includes(".registry-table"));
assert.ok(css.includes("@media(max-width:830px)"),"Mobile filters missing");
assert.ok(!map.includes("vdktree-demo-v020"),"Local fake markers must be removed");
assert.ok(homepage.includes('href="./registry.html"'),"Map must link registry");
assert.ok(homepage.includes('v1.1.0'),"Version in top right missing");
console.log("v1.1.0 registry UI and old-demo removal contract passed");
