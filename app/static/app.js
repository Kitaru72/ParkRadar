const state = {
  lastQuery: "",
  lastResult: null,
  tripSessionId: null,
  notifications: [],
  notificationTimer: null,
};

const elements = {
  searchForm: document.querySelector("#search-form"),
  searchButton: document.querySelector("#search-button"),
  demoButton: document.querySelector("#demo-button"),
  query: document.querySelector("#query"),
  radius: document.querySelector("#radius"),
  availabilityBadge: document.querySelector("#availability-badge"),
  resultEmpty: document.querySelector("#result-empty"),
  resultContent: document.querySelector("#result-content"),
  statsGrid: document.querySelector("#stats-grid"),
  classGrid: document.querySelector("#class-grid"),
  sourceGrid: document.querySelector("#source-grid"),
  startTrip: document.querySelector("#start-trip"),
  refreshNotifications: document.querySelector("#refresh-notifications"),
  cancelTrip: document.querySelector("#cancel-trip"),
  eta: document.querySelector("#eta"),
  tripMeta: document.querySelector("#trip-meta"),
  notifications: document.querySelector("#notifications"),
};

function fmtDate(value) {
  if (!value) return "нет данных";
  return new Date(value).toLocaleString("ru-RU");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setLoading(loading) {
  elements.searchButton.disabled = loading;
  elements.searchButton.textContent = loading ? "Ищем..." : "Запустить поиск";
}

function renderStats(result, location) {
  const stats = [
    { label: "Свободных мест", value: result.total_free },
    { label: "Статус availability", value: result.availability_bucket },
    { label: "Камер в радиусе", value: result.cameras_considered },
    { label: "Обновлено", value: fmtDate(result.latest_update) },
  ];
  elements.statsGrid.innerHTML = stats
    .map(
      (item) => `
        <div class="stat-card">
          <span class="muted">${escapeHtml(item.label)}</span>
          <span class="stat-value">${escapeHtml(item.value)}</span>
          <div class="muted" style="margin-top: 8px;">${escapeHtml(location.resolved_address)}</div>
        </div>
      `,
    )
    .join("");
}

function renderClasses(byClass) {
  const total = Object.values(byClass).reduce((sum, value) => sum + value, 0) || 1;
  elements.classGrid.innerHTML = Object.entries(byClass)
    .map(([name, value]) => {
      const width = Math.round((value / total) * 100);
      return `
        <div class="stat-card">
          <span class="muted">Класс ${escapeHtml(name)}</span>
          <span class="stat-value">${value}</span>
          <div class="bar"><span style="width:${width}%"></span></div>
        </div>
      `;
    })
    .join("");
}

function statusBadge(status) {
  return `<span class="status-${escapeHtml(status)}">${escapeHtml(status)}</span>`;
}

function renderSources(sources) {
  elements.sourceGrid.innerHTML = sources.length
    ? sources
        .map(
          (source) => `
            <article class="source-card">
              <div class="panel-header">
                <div>
                  <h3 style="font-size: 18px;">${escapeHtml(source.camera_name)}</h3>
                  <p class="muted">${escapeHtml(source.courtyard_name)}</p>
                </div>
                ${statusBadge(source.status)}
              </div>
              <div class="muted">Расстояние: ${source.distance_m} м</div>
              <div class="muted">Свободных мест: ${source.total_free}</div>
              <div class="muted">Обновление: ${fmtDate(source.latest_capture_at)}</div>
              ${source.image_url ? `<a class="inline-tag" href="${escapeHtml(source.image_url)}" target="_blank" rel="noreferrer">Скриншот test mode</a>` : ""}
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">В указанном радиусе нет камер из demo-реестра.</div>`;
}

function renderSearch(data) {
  state.lastResult = data;
  elements.resultEmpty.hidden = true;
  elements.resultContent.hidden = false;
  elements.availabilityBadge.textContent = data.search.availability_bucket;
  renderStats(data.search, data.location);
  renderClasses(data.search.by_class);
  renderSources(data.search.sources);
  elements.startTrip.disabled = false;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || "Произошла ошибка");
  }
  return data;
}

async function performSearch(queryOverride = null) {
  const query = (queryOverride || elements.query.value).trim();
  const radius = elements.radius.value;
  if (!query) return;
  state.lastQuery = query;
  setLoading(true);
  try {
    const data = await fetchJson(`/parking/search?q=${encodeURIComponent(query)}&radius_m=${encodeURIComponent(radius)}`);
    renderSearch(data.data);
  } catch (error) {
    elements.availabilityBadge.textContent = "Ошибка поиска";
    elements.resultEmpty.hidden = false;
    elements.resultContent.hidden = true;
    elements.resultEmpty.textContent = error.message;
  } finally {
    setLoading(false);
  }
}

function renderNotifications(items) {
  if (!items.length) {
    elements.notifications.innerHTML = `<div class="empty-state">Пока уведомлений нет. Запустите мониторинг и обновите availability через админку.</div>`;
    return;
  }
  elements.notifications.innerHTML = items
    .map(
      (item) => `
        <div class="timeline-item ${item.read_at ? "" : "unread"}">
          <div class="panel-header">
            <div>
              <h3 style="font-size:18px;">${escapeHtml(item.title)}</h3>
              <p class="muted">${escapeHtml(item.body)}</p>
            </div>
            <span class="inline-tag">${escapeHtml(item.delivery_channel)}</span>
          </div>
          <div class="muted">Создано: ${fmtDate(item.created_at)}</div>
        </div>
      `,
    )
    .join("");
}

async function refreshNotifications() {
  if (!state.tripSessionId) return;
  const data = await fetchJson(`/trip-monitoring/notifications/pull?trip_session_id=${encodeURIComponent(state.tripSessionId)}`);
  state.notifications = data.data;
  renderNotifications(state.notifications);
  const unreadIds = state.notifications.filter((item) => !item.read_at).map((item) => item.id);
  if (unreadIds.length) {
    await fetchJson("/trip-monitoring/notifications/read", {
      method: "POST",
      body: JSON.stringify({ notification_ids: unreadIds }),
    });
  }
}

async function startTripMonitoring() {
  if (!state.lastQuery) return;
  const etaMinutes = Number(elements.eta.value || 20);
  const data = await fetchJson("/trip-monitoring/sessions", {
    method: "POST",
    body: JSON.stringify({ query: state.lastQuery, eta_minutes: etaMinutes, push_enabled: false }),
  });
  state.tripSessionId = data.data.trip_session_id;
  elements.tripMeta.textContent = `Сессия ${state.tripSessionId} активна. ETA: ${data.data.eta_minutes} мин. Начальное число свободных мест: ${data.data.initial_total_free}.`;
  elements.refreshNotifications.disabled = false;
  elements.cancelTrip.disabled = false;
  await refreshNotifications();
  if (state.notificationTimer) clearInterval(state.notificationTimer);
  state.notificationTimer = setInterval(refreshNotifications, 15000);
}

async function cancelTripMonitoring() {
  if (!state.tripSessionId) return;
  await fetchJson(`/trip-monitoring/sessions/${encodeURIComponent(state.tripSessionId)}/cancel`, { method: "POST" });
  elements.tripMeta.textContent = `Сессия ${state.tripSessionId} остановлена.`;
  state.tripSessionId = null;
  elements.cancelTrip.disabled = true;
  elements.refreshNotifications.disabled = true;
  if (state.notificationTimer) clearInterval(state.notificationTimer);
}

elements.searchForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  await performSearch();
});

elements.demoButton?.addEventListener("click", async () => {
  elements.query.value = "Екатеринбург, улица Малышева 51";
  await performSearch(elements.query.value);
});

elements.startTrip?.addEventListener("click", startTripMonitoring);
elements.refreshNotifications?.addEventListener("click", refreshNotifications);
elements.cancelTrip?.addEventListener("click", cancelTripMonitoring);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => null));
}
