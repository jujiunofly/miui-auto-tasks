const $ = (id) => document.getElementById(id);

const state = {
  runId: null,
  after: 0,
  entries: new Map(),
  level: "ALL",
  autoScroll: true,
  running: false,
  lastRun: {},
  accounts: [],
  accountsKey: "",
  telegram: {},
  telegramKey: "",
  captchaMode: "browser",
  settingsData: null,
  pendingCaptcha: null,
  captchaSubmittedId: "",
  captchaDismissedId: "",
  toastTimer: null,
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  let payload = {};
  try {
    payload = await response.json();
  } catch (_) {
    payload = {};
  }
  if (!response.ok) {
    const error = new Error(payload.detail || `请求失败 (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

function toast(message, type = "") {
  const node = $("toast");
  node.textContent = message;
  node.className = `toast ${type}`.trim();
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => node.classList.add("hidden"), 3600);
}

function statusText(status) {
  return {
    running: "运行中",
    success: "已完成",
    error: "失败",
  }[status] || "待运行";
}

function captchaModeText(mode) {
  if (mode?.startsWith("auto:")) return `自动打码 (${mode.split(":")[1]})`;
  return mode === "web" ? "网页自动回传" : "本机浏览器自动捕获";
}

function setStatus(running, lastRun) {
  const pill = $("statusPill");
  const status = running ? "running" : (lastRun?.status || "idle");
  pill.className = `pill ${status}`;
  pill.textContent = running ? "运行中" : statusText(status);
  $("runBtn").disabled = running;
  $("runBtn").textContent = running ? "运行中..." : "立即运行";
  $("lastStatus").textContent = statusText(lastRun?.status);
  $("lastStarted").textContent = lastRun?.started || "暂无";
  $("lastFinished").textContent = lastRun?.finished || "暂无";
  $("subtitle").textContent = running
    ? "任务运行中，日志实时更新"
    : lastRun?.finished
      ? "上次运行已结束"
      : "正在等待任务运行";
}

function renderAccounts(accounts) {
  const key = JSON.stringify({ accounts, running: state.running });
  if (key === state.accountsKey) return;
  state.accountsKey = key;
  state.accounts = accounts;
  const root = $("accounts");
  root.innerHTML = "";
  $("accountCount").textContent = `${accounts.length} 个账号`;

  accounts.forEach((account) => {
    const card = document.createElement("div");
    card.className = "account";

    const head = document.createElement("div");
    head.className = "account-head";
    const name = document.createElement("div");
    name.className = "account-name";
    name.innerHTML = '<span class="account-dot"></span>';
    const nameText = document.createElement("span");
    nameText.textContent = `账号 ${account.index + 1}`;
    name.appendChild(nameText);
    const uid = document.createElement("span");
    uid.className = "account-uid";
    uid.textContent = account.uid;
    head.append(name, uid);

    const grid = document.createElement("div");
    grid.className = "task-grid";
    account.tasks.forEach((task) => {
      const label = document.createElement("label");
      label.className = "task-toggle";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = task.enabled;
      checkbox.dataset.task = task.key;
      checkbox.disabled = state.running;
      checkbox.addEventListener("change", () => saveAccount(account.index, card));
      const text = document.createElement("span");
      text.textContent = task.label;
      label.append(checkbox, text);
      grid.appendChild(label);
    });

    card.append(head, grid);
    root.appendChild(card);
  });
}

async function saveAccount(index, card) {
  const tasks = {};
  card.querySelectorAll("input[data-task]").forEach((input) => {
    tasks[input.dataset.task] = input.checked;
  });
  card.querySelectorAll("input[data-task]").forEach((input) => {
    input.disabled = true;
  });
  try {
    const data = await api(`/api/accounts/${index}`, {
      method: "PATCH",
      body: JSON.stringify({ tasks }),
    });
    state.accounts = data.accounts;
    state.accountsKey = "";
    renderAccounts(data.accounts);
    toast("任务开关已保存", "success");
  } catch (error) {
    toast(error.message, "error");
    state.accountsKey = "";
    renderAccounts(state.accounts);
  }
}

function renderTelegram(telegram) {
  const key = JSON.stringify({ telegram, captchaMode: state.captchaMode });
  if (key === state.telegramKey) return;
  state.telegramKey = key;
  state.telegram = telegram;
  const badge = $("tgBadge");
  badge.className = `badge ${telegram.configured ? "ok" : "warn"}`;
  badge.textContent = telegram.configured ? "Telegram 已配置" : "未配置推送";
  const info = $("telegramInfo");
  info.innerHTML = "";
  const lines = [
    `通知渠道：${telegram.notifier || "未配置"}`,
    `标题：${telegram.title || "默认"}`,
    `验证码方式：${captchaModeText(state.captchaMode)}`,
    "每次运行结束自动发送账号状态与加分汇总。",
  ];
  lines.forEach((line) => {
    const div = document.createElement("div");
    div.textContent = line;
    info.appendChild(div);
  });
}

function createField(labelText, value, options = {}) {
  const wrapper = document.createElement("div");
  wrapper.className = `field${options.full ? " full" : ""}`;
  const id = `setting-${Math.random().toString(36).slice(2)}`;
  const label = document.createElement("label");
  label.textContent = labelText;
  label.htmlFor = id;
  const input = document.createElement(options.multiline ? "textarea" : "input");
  if (!options.multiline) input.type = options.type || "text";
  input.id = id;
  input.value = value || "";
  input.placeholder = options.placeholder || "";
  input.dataset.field = options.field || "";
  if (options.multiline) input.rows = 3;
  wrapper.append(label, input);
  if (options.hint) {
    const hint = document.createElement("span");
    hint.className = "hint";
    hint.textContent = options.hint;
    wrapper.appendChild(hint);
  }
  return wrapper;
}

function createCheckboxField(labelText, checked, field) {
  const wrapper = document.createElement("label");
  wrapper.className = "checkline";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = checked;
  input.dataset.field = field;
  const text = document.createElement("span");
  text.textContent = labelText;
  wrapper.append(input, text);
  return wrapper;
}

function renderSettings(data) {
  state.settingsData = data;
  const root = $("settingsContent");
  root.innerHTML = "";

  const note = document.createElement("div");
  note.className = "settings-note";
  note.textContent = `验证码方式：${captchaModeText(data.captcha_mode)}。修改账号资料后，下次运行生效。`;
  root.appendChild(note);

  data.accounts.forEach((account) => {
    const section = document.createElement("div");
    section.className = "settings-section";
    section.dataset.accountIndex = account.index;
    const title = document.createElement("h3");
    title.textContent = `账号 ${account.index + 1}`;
    section.appendChild(title);

    const grid = document.createElement("div");
    grid.className = "settings-grid";
    grid.append(
      createField("社区 UID", account.uid, { field: "uid" }),
      createField("新密码", "", {
        field: "password",
        type: "password",
        placeholder: account.has_password ? "已设置，留空保持现有" : "未设置",
      }),
      createField("Cookies", "", {
        field: "cookies",
        multiline: true,
        full: true,
        placeholder: account.has_cookies
          ? `已配置 ${account.cookie_count} 项，留空保持现有`
          : "未配置，粘贴完整 Cookie 字符串",
        hint: "格式：key=value; key2=value2",
      }),
      createField("User-Agent", account.user_agent || "", {
        field: "user_agent",
        full: true,
      }),
      createField("登录 User-Agent", account.login_user_agent || "", {
        field: "login_user_agent",
        full: true,
      }),
      createField("设备代号", account.device || "", { field: "device" }),
      createField("设备型号", account.device_model || "", {
        field: "device_model",
      }),
    );
    section.appendChild(grid);
    root.appendChild(section);
  });

  const push = document.createElement("div");
  push.className = "settings-section";
  const pushTitle = document.createElement("h3");
  pushTitle.textContent = "Telegram 推送";
  push.appendChild(pushTitle);
  const pushGrid = document.createElement("div");
  pushGrid.className = "settings-grid";
  pushGrid.append(
    createField("通知渠道", data.onepush.notifier || "", {
      field: "onepush_notifier",
      placeholder: "例如 telegram",
    }),
    createField("标题", data.onepush.title || "", {
      field: "onepush_title",
    }),
    createField("Bot Token", "", {
      field: "onepush_token",
      type: "password",
      placeholder: data.onepush.has_token ? "已设置，留空保持现有" : "未设置",
    }),
    createField("User ID", data.onepush.userid || "", {
      field: "onepush_userid",
    }),
  );
  push.appendChild(pushGrid);
  push.appendChild(
    createCheckboxField("使用 Markdown", data.onepush.markdown, "onepush_markdown"),
  );
  root.appendChild(push);
}

async function openSettings() {
  if (state.running) {
    toast("任务运行中，暂时不能修改设置", "error");
    return;
  }
  try {
    const data = await api("/api/settings");
    renderSettings(data);
    $("settingsModal").classList.remove("hidden");
  } catch (error) {
    toast(error.message, "error");
  }
}

function closeSettings() {
  $("settingsModal").classList.add("hidden");
}

async function saveSettings() {
  const accounts = [];
  document.querySelectorAll(".settings-section[data-account-index]").forEach((section) => {
    const value = (field) => section.querySelector(`[data-field="${field}"]`)?.value || "";
    const item = {
      index: Number(section.dataset.accountIndex),
      uid: value("uid"),
      user_agent: value("user_agent"),
      login_user_agent: value("login_user_agent"),
      device: value("device"),
      device_model: value("device_model"),
    };
    const password = value("password");
    const cookies = value("cookies");
    if (password) item.password = password;
    if (cookies) item.cookies = cookies;
    accounts.push(item);
  });

  const onepush = {
    notifier: $("settingsContent").querySelector('[data-field="onepush_notifier"]')?.value || "",
    title: $("settingsContent").querySelector('[data-field="onepush_title"]')?.value || "",
    userid: $("settingsContent").querySelector('[data-field="onepush_userid"]')?.value || "",
    markdown: Boolean($("settingsContent").querySelector('[data-field="onepush_markdown"]')?.checked),
  };
  const token = $("settingsContent").querySelector('[data-field="onepush_token"]')?.value || "";
  if (token) onepush.token = token;

  const button = $("settingsSave");
  button.disabled = true;
  try {
    const data = await api("/api/settings", {
      method: "PATCH",
      body: JSON.stringify({ accounts, onepush }),
    });
    state.settingsData = data;
    state.accountsKey = "";
    state.telegramKey = "";
    closeSettings();
    toast("设置已保存", "success");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

function levelClass(level) {
  return `level level-${String(level || "INFO").toUpperCase()}`;
}

function renderLogs() {
  const root = $("logList");
  const wasAtBottom = root.scrollHeight - root.scrollTop - root.clientHeight < 36;
  const previousScroll = root.scrollTop;
  const fragment = document.createDocumentFragment();
  const entries = [...state.entries.values()].sort((a, b) => a.id - b.id);
  let visible = 0;

  entries.forEach((entry) => {
    if (state.level !== "ALL" && entry.level !== state.level) return;
    visible += 1;

    const row = document.createElement("div");
    row.className = `log-row level-${String(entry.level || "INFO").toUpperCase()}`;

    const time = document.createElement("span");
    time.className = "log-time";
    time.textContent = entry.time;

    const levelCell = document.createElement("span");
    levelCell.className = "log-level-cell";
    const level = document.createElement("span");
    level.className = levelClass(entry.level);
    level.textContent = entry.level;
    levelCell.appendChild(level);

    const message = document.createElement("span");
    message.className = "log-message";
    message.textContent = entry.message;
    message.title = `${entry.module}.${entry.function}:${entry.line}`;

    row.append(time, levelCell, message);
    fragment.appendChild(row);
  });

  root.innerHTML = "";
  root.appendChild(fragment);
  $("logEmpty").classList.toggle("hidden", visible !== 0);
  if (state.autoScroll && wasAtBottom) root.scrollTop = root.scrollHeight;
  else root.scrollTop = previousScroll;
}

function addLogs(logs) {
  if (!logs?.length) return;
  logs.forEach((entry) => {
    if (state.entries.has(entry.id)) return;
    state.entries.set(entry.id, entry);
    state.after = Math.max(state.after, entry.id);
  });
  renderLogs();
}

function buildRelayUrl(item) {
  if (!item?.url || !item?.relay_token) return item?.url || "";
  const source = new URL(item.url);
  const params = new URLSearchParams(source.search);
  params.set("id", item.id);
  params.set("relay_token", item.relay_token);
  return `${location.origin}/v2/html/check.html?${params.toString()}`;
}

function openCaptchaModal() {
  if (!state.pendingCaptcha) return;
  $("captchaCommand").textContent = `python captcha_helper.py --server ${location.origin}`;
  $("captchaLink").href = state.pendingCaptcha.url;
  $("captchaRelayLink").href = buildRelayUrl(state.pendingCaptcha);
  $("captchaStatus").textContent = "等待验证...";
  $("captchaValue").value = "";
  $("captchaModal").classList.remove("hidden");
}

function openCaptchaWindow() {
  if (!state.pendingCaptcha) return;
  const url = buildRelayUrl(state.pendingCaptcha);
  if (!url) {
    toast("验证链接无效，请重试", "error");
    return;
  }
  const popup = window.open(
    url,
    "miui-captcha-verify",
    "popup=yes,width=520,height=760",
  );
  if (!popup) {
    toast("浏览器拦截了弹窗，请允许弹窗后重试", "error");
    return;
  }
  $("captchaStatus").textContent = "验证完成后会自动返回...";
}

async function copyCaptchaCommand() {
  const text = $("captchaCommand").textContent;
  let copied = false;
  try {
    await navigator.clipboard.writeText(text);
    copied = true;
  } catch (_) {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    copied = document.execCommand("copy");
    area.remove();
  }
  toast(copied ? "命令已复制" : "复制失败，请手动选择命令", copied ? "success" : "error");
}

function closeCaptchaModal() {
  $("captchaModal").classList.add("hidden");
  if (state.pendingCaptcha) state.captchaDismissedId = state.pendingCaptcha.id;
}

function syncCaptcha(pending) {
  const item = pending?.[0] || null;
  state.pendingCaptcha = item;
  $("captchaBtn").classList.toggle("hidden", !item);
  if (!item) {
    state.captchaSubmittedId = "";
    state.captchaDismissedId = "";
    closeCaptchaModal();
    return;
  }
  if (item.id !== state.captchaSubmittedId && item.id !== state.captchaDismissedId) {
    const modalHidden = $("captchaModal").classList.contains("hidden");
    if (modalHidden) openCaptchaModal();
  }
}

async function submitCaptcha() {
  if (!state.pendingCaptcha) return;
  const value = $("captchaValue").value.trim();
  if (!value) {
    toast("请粘贴回调 URL 或 token", "error");
    return;
  }
  const button = $("captchaSubmit");
  button.disabled = true;
  try {
    await api("/api/captcha/submit", {
      method: "POST",
      body: JSON.stringify({ id: state.pendingCaptcha.id, value }),
    });
    state.captchaSubmittedId = state.pendingCaptcha.id;
    closeCaptchaModal();
    toast("验证码已提交，任务继续执行", "success");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function runTask() {
  const button = $("runBtn");
  button.disabled = true;
  try {
    await api("/api/run", { method: "POST" });
    state.entries.clear();
    state.after = 0;
    state.runId = null;
    state.captchaSubmittedId = "";
    renderLogs();
    toast("任务已启动", "success");
  } catch (error) {
    toast(error.message, "error");
    button.disabled = false;
  }
}

async function poll() {
  try {
    const data = await api(`/api/state?after=${state.after}`);
    if (state.runId === null) {
      state.runId = data.run_id;
    } else if (state.runId !== data.run_id) {
      state.runId = data.run_id;
      state.entries.clear();
      state.after = 0;
      state.captchaSubmittedId = "";
    }
    state.running = data.running;
    state.lastRun = data.last_run || {};
    state.captchaMode = data.captcha_mode || "browser";
    renderAccounts(data.accounts || []);
    renderTelegram(data.telegram || {});
    setStatus(state.running, state.lastRun);
    addLogs(data.logs || []);
    syncCaptcha(data.captcha || []);
  } catch (error) {
    if (error.status !== 401) toast(error.message, "error");
  } finally {
    setTimeout(poll, 1200);
  }
}

$("runBtn").addEventListener("click", runTask);
$("settingsBtn").addEventListener("click", openSettings);
$("settingsClose").addEventListener("click", closeSettings);
$("settingsCancel").addEventListener("click", closeSettings);
$("settingsSave").addEventListener("click", saveSettings);
$("levelFilter").addEventListener("change", (event) => {
  state.level = event.target.value;
  renderLogs();
});
$("autoScroll").addEventListener("change", (event) => {
  state.autoScroll = event.target.checked;
});
$("captchaBtn").addEventListener("click", openCaptchaModal);
$("captchaOpen").addEventListener("click", openCaptchaWindow);
$("captchaCopy").addEventListener("click", copyCaptchaCommand);
$("captchaClose").addEventListener("click", closeCaptchaModal);
$("captchaLater").addEventListener("click", closeCaptchaModal);
$("captchaSubmit").addEventListener("click", submitCaptcha);
$("captchaModal").addEventListener("click", (event) => {
  if (event.target === $("captchaModal")) closeCaptchaModal();
});
$("settingsModal").addEventListener("click", (event) => {
  if (event.target === $("settingsModal")) closeSettings();
});

window.addEventListener("message", (event) => {
  if (event.origin !== location.origin) return;
  const data = event.data || {};
  if (data.type !== "captcha-complete") return;
  if (data.ok) {
    $("captchaStatus").textContent = "验证成功，正在继续...";
    setTimeout(() => {
      if (state.pendingCaptcha) state.captchaDismissedId = "";
      closeCaptchaModal();
    }, 700);
  } else {
    $("captchaStatus").textContent = "验证未完成，请重试";
  }
});

poll();
