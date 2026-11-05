/* v0.4.2 — smoke tests for first-time MAX login UI, without browser packages. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const source = fs.readFileSync(path.resolve(__dirname, "../auth/client.js"), "utf8");

function element(tag = "div") {
  return {
    tag,
    children: [],
    open: false,
    textContent: "",
    cached: new Map(),
    _html: "",
    get innerHTML() { return this._html; },
    set innerHTML(value) { this._html = value; this.children = []; this.cached = new Map(); },
    append(child) { this.children.push(child); },
    setAttribute(name, value) { this[name] = value; },
    querySelector(selector) {
      if (this.tag === "dialog" && this.children[0]) return this.children[0].querySelector(selector);
      if (!this.cached.has(selector)) this.cached.set(selector, element(selector));
      return this.cached.get(selector);
    },
    showModal() { this.open = true; },
    close() { this.open = false; },
    insertBefore(child) { this.authButton = child; }
  };
}

async function render(config = {}) {
  const header = element("header");
  const dialogElements = [];
  const apiRequests = [];
  const storage = new Map();
  const doc = {
    querySelector(s) { return s === "header" ? header : null; },
    createElement(tag) { return element(tag); },
    body: {append(el) {dialogElements.push(el); }}
  };
  const win = {
    VDK_AUTH_API: "https://vdktree.bothost.tech",
    location: {hash: config.hash || ""},
    ...(config.bridge ? {WebApp: config.bridge} : {})
  };
  const context = {
    window: win, document: doc, URLSearchParams,
    sessionStorage: {
      getItem(key) { return storage.get(key) || null; },
      setItem(key,value) { storage.set(key,value); },
      removeItem(key) { storage.delete(key); }
    },
    fetch: async (url,opts) => {
      apiRequests.push({url,opts});
      return {ok: true, json: async () => ({
        token: "SESSION_TEST_ONLY",
        user: {id:"user-1", display_name:"Тест MAX", role:"user",
               login:null, has_password:false}
      })};
    },
    console: {error() {}}
  };
  vm.runInNewContext(source, context, {filename:"auth/client.js"});
  await new Promise(resolve => setImmediate(resolve));
  return {header, dialog: dialogElements[0], apiRequests, storage, win};
}

async function main() {
  // Ordinary web visitor sees clear MAX-first instructions, not an obligatory login form.
  const web = await render();
  assert.equal(web.apiRequests.length, 0);
  web.header.authButton.onclick();
  const panel = web.dialog.children[0];
  assert.match(panel.innerHTML, /Логин и пароль не нужны/);
  assert.match(panel.innerHTML, /Деревья Владивостока/);
  assert.match(panel.innerHTML, /Перейти в MAX/);
  assert.match(panel.innerHTML, /<details class="vdk-existing-login">/);
  assert.match(panel.innerHTML, /У меня уже есть логин и пароль/);
  await panel.querySelector("#vdk-try-max").onclick();
  assert.match(panel.querySelector("#vdk-auth-error").textContent, /Данные MAX не получены/);
  assert.equal(web.apiRequests.length, 0);

  // A real MAX Bridge launch should call the /max endpoint, not ask for old credentials.
  const signed = "auth_date=1730832000&user=%7B%22id%22%3A123%7D&hash=abcdef";
  let readyCalled = false;
  const max = await render({bridge:{initData:signed, ready:()=>{readyCalled=true;}}});
  assert.equal(readyCalled, true);
  assert.equal(max.apiRequests.length, 1);
  assert.match(max.apiRequests[0].url, /\/api\/auth\/max$/);
  assert.equal(JSON.parse(max.apiRequests[0].opts.body).init_data, signed);
  assert.equal(max.header.authButton.textContent, "Тест MAX");
  assert.match(max.dialog.children[0].querySelector("#vdk-create-credentials").innerHTML, /Создайте логин и пароль/);

  // Official fallback for clients that pass signed WebAppData in URL hash.
  const fromHash = await render({hash:"#WebAppData="+encodeURIComponent(signed)+"&WebAppPlatform=web"});
  assert.equal(fromHash.apiRequests.length, 1);
  assert.equal(JSON.parse(fromHash.apiRequests[0].opts.body).init_data, signed);
  console.log("MAX-first UI checks: 3 passed");
}

main().catch(e=>{console.error(e);process.exitCode=1;});
