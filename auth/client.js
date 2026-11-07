// VdkTree v1.0.2 — MAX Mini App browser pairing and optional 8-character password.
(() => {
  "use strict";
  const api = String(window.VDK_AUTH_API || "").replace(/\/$/, "");
  const storageKey = "vdktree-auth-session-v040";
  let token = "";
  let user = null;
  let pairing = null;
  let pairingTimer = null;
  let pairingBusy = false;
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

  function notifyLogin() {
    if (typeof window.dispatchEvent === "function" && typeof Event === "function")
      window.dispatchEvent(new Event("vdktree:auth"));
  }
  function stopPairing() {
    if (pairingTimer !== null) clearInterval(pairingTimer);
    pairingTimer = null;
    pairing = null;
  }
  function saveSession(data) {
    stopPairing();
    token = data.token;
    user = data.user;
    try { sessionStorage.setItem(storageKey, token); } catch (_) {}
    drawButton();
    notifyLogin();
  }
  function clearSession() {
    stopPairing();
    token = ""; user = null;
    try { sessionStorage.removeItem(storageKey); } catch (_) {}
    drawButton();
    notifyLogin();
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
        <p><strong>Впервые здесь? Логин и пароль не нужны!</strong></p>
        <ol class="vdk-auth-steps">
          <li>Откройте мессенджер <strong>MAX</strong>.</li>
          <li>Перейдите в чат бота «Деревья Владивостока» по кнопке ниже.</li>
          <li>Нажмите в чате кнопку <strong>«Открыть»</strong> для запуска мини-приложения.</li>
        </ol>
        <a class="vdk-auth-open-max" href="https://max.ru/id2540275814_1_bot" target="_blank" rel="noopener noreferrer">Открыть бота в MAX</a>
        <p class="minor">Внутри мини-приложения MAX вход происходит автоматически. Для входа с обычного браузера используйте одноразовый код.</p>
        <button type="button" id="vdk-try-max" class="secondary">Войти через MAX по коду</button>
        <div id="vdk-max-pair" class="vdk-max-pair" hidden>
          <p><strong>Ваш код для входа:</strong></p>
          <div id="vdk-pair-code" class="vdk-pair-code" aria-live="polite"></div>
          <p>Откройте мини-приложение VdkTree через бота MAX, нажмите «Войти» (или профиль), выберите «Подтвердить вход в браузере» и введите этот код. Вернитесь сюда — вход выполнится автоматически.</p>
          <p class="minor">Код действует 5 минут. Никому не передавайте его.</p>
        </div>
        <details class="vdk-existing-login">
          <summary>У меня уже есть логин и пароль</summary>
          <form id="vdk-login-form">
            <label>Логин<input name="login" autocomplete="username" minlength="4" required></label>
            <label>Пароль<input name="password" type="password" autocomplete="current-password" required></label>
            <button type="submit">Войти по логину</button>
          </form>
        </details>
        <p role="alert" class="error" id="vdk-auth-error"></p>
        <button class="secondary vdk-auth-dismiss" type="button" id="vdk-close">Закрыть</button>`;
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
      panel.querySelector("#vdk-close").onclick = () => { stopPairing(); dialog.close(); };
      panel.querySelector("#vdk-try-max").onclick = startBrowserPairing;
    } else {
      panel.innerHTML = `
        <h2>Мой профиль</h2>
        <p id="vdk-user-greeting"></p>
        <div id="vdk-create-credentials"></div>
        <div id="vdk-max-approve"></div>
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
            <label>Пароль (не менее 8 символов)
              <input name="password" type="password" minlength="8" maxlength="128" autocomplete="new-password" required>
            </label>
            <label>Повторите пароль
              <input name="confirm" type="password" minlength="8" maxlength="128" autocomplete="new-password" required>
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
      // A browser code can only be approved while running inside the signed MAX Mini App.
      if (signedLaunchData()) {
        const approval = panel.querySelector("#vdk-max-approve");
        approval.innerHTML = `
          <h3>Подтвердить вход в браузере</h3>
          <p class="minor">Откройте сайт VdkTree в обычном браузере, нажмите «Войти через MAX по коду», затем введите показанный там код здесь. Подтверждайте только свой вход.</p>
          <form id="vdk-approve-form">
            <label>Код из браузера
              <input name="code" maxlength="12" autocomplete="off" autocapitalize="characters" required placeholder="8 символов">
            </label>
            <button type="submit">Подтвердить вход в браузере</button>
          </form>
          <p id="vdk-approve-status" role="status" class="minor"></p>`;
        approval.querySelector("form").onsubmit = async event => {
          event.preventDefault();
          const status = approval.querySelector("#vdk-approve-status");
          const code = event.currentTarget.elements.code.value.trim().toUpperCase();
          status.textContent = "Подтверждаем...";
          try {
            await send("device/approve", {code, init_data: signedLaunchData()});
            status.textContent = "Вход подтверждён. Вернитесь в браузер — авторизация произойдёт автоматически.";
          } catch (e) { status.textContent = e.message; }
        };
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

  async function startBrowserPairing() {
    stopPairing();
    const error = dialog.querySelector("#vdk-auth-error");
    const section = dialog.querySelector("#vdk-max-pair");
    if (error) error.textContent = "Создаём одноразовый код...";
    try {
      const result = await send("device/start");
      pairing = {id:result.request_id,verifier:result.verifier};
      section.hidden = false;
      section.querySelector("#vdk-pair-code").textContent = result.code;
      if (error) error.textContent = "Ожидаем подтверждение через MAX...";
      pairingTimer = setInterval(() => { void checkBrowserPairing(); }, 2000);
    } catch (e) {
      if (error) error.textContent = e.message;
    }
  }

  async function checkBrowserPairing() {
    if (!pairing || pairingBusy || user) return;
    pairingBusy = true;
    const requested = pairing;
    try {
      const result = await send("device/poll", {
        request_id:requested.id, verifier:requested.verifier
      });
      if (pairing !== requested) return;
      if (result.status === "authenticated") {
        saveSession(result);
        if (dialog.open) draw();
      }
    } catch (e) {
      if (pairing !== requested) return;
      stopPairing();
      const error = dialog.querySelector("#vdk-auth-error");
      if (error) error.textContent = e.message;
    } finally { pairingBusy = false; }
  }

  // Only signed launch data is sent to BotHost. Never authenticate using initDataUnsafe.
  function signedLaunchData() {
    const raw = window.WebApp?.initData;
    if (typeof raw === "string" && raw.length > 0) return raw;
    // Official MAX docs also expose the same signed WebAppData in the URL hash.
    // Fallback helps when Bridge is unavailable or initializes later.
    try {
      const fragment = new URLSearchParams(window.location.hash.slice(1));
      return fragment.get("WebAppData") || "";
    } catch (_) { return ""; }
  }

  async function loginWithMAX() {
    const raw = signedLaunchData();
    if (!raw) {
      if (!dialog.open) show();
      const error = dialog.querySelector("#vdk-auth-error");
      if (error) error.textContent = "Данные MAX не получены. Закройте сайт, откройте чат с ботом в MAX и нажмите «Открыть». Прямой адрес сайта не выполняет вход через MAX.";
      return false;
    }
    try {
      const result = await send("max", {init_data: raw});
      saveSession(result);
      if (!dialog.open && !user.has_password) show();
      else if (dialog.open) draw();
      return true;
    } catch (e) {
      console.error("MAX login failed:", e.message);
      if (!user && !dialog.open) show();
      const error = dialog.querySelector("#vdk-auth-error");
      if (error) error.textContent = "Не удалось войти через MAX: " + e.message;
      return false;
    }
  }

  async function init() {
    try { window.WebApp?.ready?.(); } catch (_) {}
    if (token) {
      try {
        const result = await send("me", undefined, "GET");
        user = result.user; drawButton(); notifyLogin();
      } catch (_) { clearSession(); }
    }
    if (signedLaunchData()) await loginWithMAX();
  }
  void init();
})();
