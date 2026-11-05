// VdkTree v0.4.0 — MAX login and optional username/password for returning users.
(() => {
  "use strict";
  const api = String(window.VDK_AUTH_API || "").replace(/\/$/, "");
  const storageKey = "vdktree-auth-session-v040";
  let token = "";
  let user = null;
  try { token = sessionStorage.getItem(storageKey) || ""; } catch (_) {}

  const header = document.querySelector("header");
  const version = header?.querySelector(".version");
  if (!header || !version) return;
  const button = document.createElement("button");
  button.className = "vdk-auth-btn";
  button.type = "button";
  button.textContent = "Войти";
  header.insertBefore(button, version);

  const dialog = document.createElement("dialog");
  dialog.id = "vdk-auth-dialog";
  dialog.setAttribute("aria-label", "Вход в Деревья Владивостока");
  document.body.append(dialog);

  let status = "";
  function saveSession(data) {
    token = data.token;
    user = data.user;
    try { sessionStorage.setItem(storageKey, token); } catch (_) {}
    drawButton();
  }
  function clearSession() {
    token = ""; user = null;
    try { sessionStorage.removeItem(storageKey); } catch (_) {}
    drawButton();
  }
  function drawButton() {
    button.textContent = user ? (user.display_name || user.login || "Профиль") : "Войти";
    button.title = user ? "Мой профиль" : "Войти в сервис";
  }
  async function send(path, data, method = "POST") {
    if (!api) throw new Error("Адрес сервера BotHost ещё не настроен");
    const headers = {};
    if (data !== undefined) headers["Content-Type"] = "application/json";
    if (token) headers.Authorization = "Bearer " + token;
    let response;
    try {
      response = await fetch(api + "/api/auth/" + path, {
        method, headers, body: data === undefined ? undefined : JSON.stringify(data),
        cache: "no-store"
      });
    } catch (_) { throw new Error("Сервер BotHost пока недоступен"); }
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = result.detail;
      throw new Error(typeof detail === "string" ? detail : "Ошибка авторизации (" + response.status + ")");
    }
    return result;
  }
  function show() {
    status = "";
    draw();
    if (!dialog.open) dialog.showModal();
  }
  function draw() {
    dialog.innerHTML = "";
    const panel = document.createElement("div");
    dialog.append(panel);
    if (!user) {
      panel.innerHTML = `
        <h2>Вход в VdkTree</h2>
        <p>Первый вход — через бота MAX. После этого вы сможете создать логин и пароль для входа с сайта.</p>
        <p class="minor">Если вы уже создавали логин и пароль, введите их ниже.</p>
        <form id="vdk-login-form">
          <label>Логин<input name="login" autocomplete="username" minlength="4" required></label>
          <label>Пароль<input name="password" type="password" autocomplete="current-password" required></label>
          <button type="submit">Войти по логину</button>
        </form>
        <p class="minor">Для первого входа откройте VdkTree из мини-приложения MAX.</p>
        <button class="secondary" type="button" id="vdk-close">Закрыть</button>
        <p role="alert" class="error" id="vdk-auth-error"></p>`;
      panel.querySelector("#vdk-login-form").onsubmit = async event => {
        event.preventDefault();
        const form = event.currentTarget;
        const error = panel.querySelector("#vdk-auth-error");
        error.textContent = "Проверяем...";
        try {
          const answer = await send("password", {
            login: form.elements.login.value.trim(),
            password: form.elements.password.value
          });
          saveSession(answer);
          draw();
        } catch (e) { error.textContent = e.message; }
      };
      panel.querySelector("#vdk-close").onclick = () => dialog.close();
    } else {
      panel.innerHTML = `
        <h2>Мой профиль</h2>
        <p id="vdk-user-greeting"></p>
        <div id="vdk-create-credentials"></div>
        <button type="button" id="vdk-logout" class="secondary">Выйти</button>
        <button type="button" id="vdk-close" class="secondary">Закрыть</button>
        <p role="alert" class="error" id="vdk-auth-error"></p>`;
      panel.querySelector("#vdk-user-greeting").textContent = "Вы вошли как " + (user.display_name || user.login || "участник");
      if (!user.has_password) {
        const setup = panel.querySelector("#vdk-create-credentials");
        setup.innerHTML = `
          <p><strong>Создайте логин и пароль</strong>, чтобы входить без открытия MAX.</p>
          <form id="vdk-credentials-form">
            <label>Новый логин (латиница, 4–32 символа)
              <input name="login" minlength="4" maxlength="32" pattern="[A-Za-z0-9_-]+" autocomplete="username" required>
            </label>
            <label>Пароль (не менее 12 символов)
              <input name="password" type="password" minlength="12" maxlength="128" autocomplete="new-password" required>
            </label>
            <label>Повторите пароль
              <input name="confirm" type="password" minlength="12" maxlength="128" autocomplete="new-password" required>
            </label>
            <button type="submit">Сохранить логин и пароль</button>
          </form>
          <p class="minor">Это необязательно. Вы можете продолжать входить через MAX.</p>`;
        setup.querySelector("form").onsubmit = async event => {
          event.preventDefault();
          const f = event.currentTarget.elements;
          const error = panel.querySelector("#vdk-auth-error");
          if (f.password.value !== f.confirm.value) {
            error.textContent = "Пароли не совпадают"; return;
          }
          error.textContent = "Сохраняем...";
          try {
            const answer = await send("credentials", {login: f.login.value, password: f.password.value});
            user = answer.user;
            draw();
          } catch (e) { error.textContent = e.message; }
        };
      } else {
        panel.querySelector("#vdk-create-credentials").textContent = "Логин создан: " + user.login;
      }
      panel.querySelector("#vdk-logout").onclick = async () => {
        try { await send("logout"); } catch (_) {}
        clearSession();
        draw();
      };
      panel.querySelector("#vdk-close").onclick = () => dialog.close();
    }
  }
  button.onclick = show;
  window.VdkAuth = {
    getUser: () => user,
    authorizedFetch: (path, options = {}) => fetch(api + path, {
      ...options, headers: {...(options.headers || {}), ...(token ? {Authorization:"Bearer " + token} : {})}
    })
  };

  async function init() {
    if (token) {
      try {
        const result = await send("me", undefined, "GET");
        user = result.user; drawButton();
      } catch (_) { clearSession(); }
    }
    const raw = window.WebApp?.initData;
    if (typeof raw === "string" && raw.length > 0) {
      try {
        const result = await send("max", {init_data: raw});
        saveSession(result);
        if (!user.has_password) show();
      } catch (e) {
        console.error("MAX login failed:", e.message);
        if (!user) {
          show();
          const error = dialog.querySelector("#vdk-auth-error");
          if (error) error.textContent = "Вход через MAX: " + e.message;
        }
      }
    }
  }
  void init();
})();
