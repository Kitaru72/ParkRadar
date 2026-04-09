const $ = (selector) => document.querySelector(selector);

const loginForm = $("#login-form");
const loginStatus = $("#login-status");
const cameraForm = $("#camera-form");
const snapshotForm = $("#snapshot-form");
const cameraSelect = $("#camera-select");
const cameraTable = $("#camera-table");
const adminKpis = $("#admin-kpis");

function fmtDate(value) {
  if (!value) return "нет данных";
  return new Date(value).toLocaleString("ru-RU");
}

async function fetchJson(url, options = {}) {
  const headers = options.headers || {};
  const isForm = options.body instanceof FormData;
  if (!isForm && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const response = await fetch(url, { credentials: "include", ...options, headers });
  const data = await response.json();
  if (!response.ok || data.ok === false) throw new Error(data.error || "Произошла ошибка");
  return data;
}

async function login(event) {
  event.preventDefault();
  try {
    await fetchJson("/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email: $("#email").value,
        password: $("#password").value,
      }),
    });
    loginStatus.textContent = "Сессия активна.";
    await refreshAdmin();
  } catch (error) {
    loginStatus.textContent = error.message;
  }
}

function renderKpis(requestStats, availabilityStats) {
  const cards = [
    { label: "Всего пользовательских запросов", value: requestStats.total_requests ?? 0 },
    { label: "Камер: мест много", value: availabilityStats["мест много"] ?? 0 },
    { label: "Камер: мест достаточно", value: availabilityStats["мест достаточно"] ?? 0 },
    { label: "Камер: мест мало / нет", value: (availabilityStats["мест мало"] ?? 0) + (availabilityStats["мест нет"] ?? 0) },
  ];
  adminKpis.innerHTML = cards
    .map(
      (card) => `
        <div class="stat-card">
          <span class="muted">${card.label}</span>
          <span class="stat-value">${card.value}</span>
        </div>
      `,
    )
    .join("");
}

function renderCameraRows(cameras) {
  cameraSelect.innerHTML = cameras.map((camera) => `<option value="${camera.id}">${camera.id} - ${camera.name}</option>`).join("");
  cameraTable.innerHTML = cameras
    .map(
      (camera) => `
        <tr>
          <td>${camera.id}</td>
          <td><strong>${camera.name}</strong><br /><span class="muted">${camera.notes || ""}</span></td>
          <td>${camera.courtyard_name}<br /><span class="muted">${camera.lat}, ${camera.lon}</span></td>
          <td><span class="status-${camera.status}">${camera.status}</span></td>
          <td>${fmtDate(camera.last_capture_at)}</td>
          <td>${camera.source_url || "-"}</td>
        </tr>
      `,
    )
    .join("");
}

async function refreshAdmin() {
  const [requestStats, availabilityStats, cameras] = await Promise.all([
    fetchJson("/admin/stats/requests"),
    fetchJson("/admin/stats/availability"),
    fetchJson("/admin/cameras"),
  ]);
  renderKpis(requestStats.data, availabilityStats.data);
  renderCameraRows(cameras.data);
}

async function createCamera(event) {
  event.preventDefault();
  const formData = new FormData(cameraForm);
  const payload = Object.fromEntries(formData.entries());
  try {
    await fetchJson("/admin/cameras", { method: "POST", body: JSON.stringify(payload) });
    cameraForm.reset();
    await refreshAdmin();
  } catch (error) {
    alert(error.message);
  }
}

async function uploadSnapshot(event) {
  event.preventDefault();
  const formData = new FormData(snapshotForm);
  try {
    await fetchJson("/test/screenshots", { method: "POST", body: formData });
    snapshotForm.reset();
    await refreshAdmin();
  } catch (error) {
    alert(error.message);
  }
}

$("#refresh-admin")?.addEventListener("click", refreshAdmin);
$("#run-due-check")?.addEventListener("click", async () => {
  try {
    await fetchJson("/trip-monitoring/runner/check-due", { method: "POST" });
    await refreshAdmin();
    alert("due-check выполнен");
  } catch (error) {
    alert(error.message);
  }
});

$("#logout-button")?.addEventListener("click", async () => {
  try {
    await fetchJson("/auth/logout", { method: "POST" });
    loginStatus.textContent = "Сессия завершена.";
  } catch (error) {
    alert(error.message);
  }
});

loginForm?.addEventListener("submit", login);
cameraForm?.addEventListener("submit", createCamera);
snapshotForm?.addEventListener("submit", uploadSnapshot);

fetchJson("/auth/me")
  .then(refreshAdmin)
  .catch(() => {
    loginStatus.textContent = "Сначала войдите в систему.";
  });
