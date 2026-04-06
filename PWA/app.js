const EMOTIONS = [
  "тревога", "грусть", "тоска", "гнев", "обида", "вина", "злость",
  "стыд", "страх", "раздражение", "зависть", "отчаяние", "беспокойство",
  "унижение", "отвращение", "одиночество", "беспомощность", "неуверенность",
  "ненависть", "отчуждение",
];
const NEW_EMOTIONS = ["радость", "спокойствие", "облегчение", "надежда", "гордость", "благодарность"];
const INTENSITIES = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100];
const DURATIONS = [1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 85, 90, 95, 100, 105, 110, 115, 120];

const state = {
  page: "dashboard",
  thoughts: null,
  exposure: null,
  selectedThoughtEntry: null,
  selectedExposureEntry: null,
  selectedActGroupId: null,
};

const homeBtn = document.getElementById("home-btn");
const views = {
  dashboard: document.getElementById("dashboard-view"),
  thoughts: document.getElementById("thoughts-view"),
  thoughtsCreate: document.getElementById("thoughts-create-view"),
  thoughtsHistory: document.getElementById("thoughts-history-view"),
  thoughtRecord: document.getElementById("thought-record-view"),
  thoughtsExport: document.getElementById("thoughts-export-view"),
  thoughtsBulkDelete: document.getElementById("thoughts-bulk-delete-view"),
  exposure: document.getElementById("exposure-view"),
  exposureCreate: document.getElementById("exposure-create-view"),
  exposureHistory: document.getElementById("exposure-history-view"),
  exposureExport: document.getElementById("exposure-export-view"),
  exposureBulkDelete: document.getElementById("exposure-bulk-delete-view"),
  exposureReview: document.getElementById("exposure-review-view"),
  act: document.getElementById("act-view"),
  actCollection: document.getElementById("act-collection-view"),
  achievements: document.getElementById("achievements-view"),
};

function showPage(page) {
  state.page = page;
  Object.entries(views).forEach(([key, el]) => {
    if (!el) return;
    el.classList.toggle("hidden", key !== page);
  });
  homeBtn?.classList.toggle("hidden", page === "dashboard");
  if (page === "dashboard") renderDashboard();
  if (page === "thoughtsHistory") renderThoughtHistory();
  if (page === "exposureHistory") renderExposureHistory();
  if (page === "act") renderActHub();
  if (page === "actCollection") renderActCollection(state.selectedActGroupId);
  if (page === "achievements") renderAchievements();
}

function renderDashboard() {
  const root = document.getElementById("dashboard-root");
  if (!root) return;
  const streakDays = updateVisitStreak();
  const thoughts = loadLocal("thought_entries").length;
  const exposureEntries = loadLocal("exposure_entries");
  const exposureExpected = exposureEntries.filter((e) => getExposureStatus(e) === "expected").length;
  const exposurePast = exposureEntries.filter((e) => getExposureStatus(e) === "past").length;
  const exposureCompleted = exposureEntries.filter((e) => getExposureStatus(e) === "completed").length;
  const daily = getDailyActCardEntry();
  const isTodayDaily = daily && daily.dateKey === getTodayDateKey();
  const dailyCard = isTodayDaily && daily?.cardId ? getActCardById(daily.cardId) : null;
  const actCoverSrc = dailyCard ? `./image/${dailyCard.groupId}.png` : "./image/1.png";
  const actSubtitle = dailyCard
    ? `${dailyCard.groupName} · ${dailyCard.title}`
    : "Возьмите карточку дня";
  const ach = getAchievementsProgress();
  root.innerHTML = `
    <div class="dashboard-layout">
      <div class="dashboard-left">
        <div class="dashboard-top-split">
          <div class="saved-item dashboard-tile dashboard-tile--square dashboard-tile--streak" role="status">
            <p class="dashboard-tile-title">Дни подряд</p>
            <p class="dashboard-tile-streak">${streakDays}</p>
            <p class="dashboard-tile-meta">Каждый день</p>
          </div>
          <button class="saved-item dashboard-tile dashboard-tile--square" type="button" data-dashboard-nav="achievements">
            <p class="dashboard-tile-title">Достижения</p>
            <p class="dashboard-tile-meta">${ach.unlocked} / ${ach.total}</p>
          </button>
        </div>
        <button class="saved-item dashboard-tile dashboard-tile--hbar" type="button" data-dashboard-nav="thoughts">
          <p class="dashboard-tile-title">Дневник мыслей</p>
          <p class="dashboard-tile-meta">Записей: ${thoughts}</p>
        </button>
        <button class="saved-item dashboard-tile dashboard-tile--hbar" type="button" data-dashboard-nav="exposure">
          <p class="dashboard-tile-title">Дневник экспозиции</p>
          <p class="dashboard-tile-meta">Ожидаемых: ${exposureExpected} · Прошедших: ${exposurePast} · Завершённых: ${exposureCompleted}</p>
        </button>
      </div>
      <button class="saved-item dashboard-tile dashboard-tile--act-column" type="button" data-dashboard-nav="act">
        <div class="dashboard-act-cover-wrap" aria-hidden="true">
          <img class="dashboard-act-cover" src="${actCoverSrc}" alt="" />
        </div>
        <div class="dashboard-tile-act-text">
          <p class="dashboard-tile-title">Карточка дня</p>
          <p class="dashboard-tile-meta">${escapeHtml(actSubtitle)}</p>
        </div>
      </button>
    </div>
  `;
  root.querySelectorAll("[data-dashboard-nav]").forEach((btn) => {
    btn.addEventListener("click", () => showPage(btn.dataset.dashboardNav));
  });
}

function chip(value, label, onClick, selected = false) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = `chip${selected ? " selected" : ""}`;
  b.textContent = label ?? value;
  b.addEventListener("click", () => onClick(value));
  return b;
}

function createInputField(label, value = "", type = "text", placeholder = "") {
  const wrap = document.createElement("div");
  wrap.className = "field";
  const l = document.createElement("label");
  l.textContent = label;
  const input = type === "textarea" ? document.createElement("textarea") : document.createElement("input");
  if (type !== "textarea") input.type = type;
  input.value = value;
  input.placeholder = placeholder;
  wrap.append(l, input);
  return { wrap, input };
}

/**
 * @param {{ badge?: string, title: string, hint: string, helpModal?: { title: string, body: string } }} meta
 */
function createWizard(rootId, meta) {
  const root = document.getElementById(rootId);
  root.innerHTML = "";
  const card = document.createElement("div");
  card.className = "wizard glass";
  if (meta.helpModal) card.classList.add("wizard--has-help");
  const header = document.createElement("div");
  header.className = "wizard-header";
  if (meta.badge) {
    const badge = document.createElement("div");
    badge.className = "step-badge";
    badge.textContent = meta.badge;
    header.appendChild(badge);
  }
  const h3 = document.createElement("h3");
  h3.textContent = meta.title;
  const p = document.createElement("p");
  p.className = "hint";
  p.textContent = meta.hint;
  header.append(h3, p);
  const body = document.createElement("div");
  body.className = "step-body";
  card.append(header, body);
  root.appendChild(card);
  card._body = body;
  if (meta.helpModal) {
    const helpBtn = document.createElement("button");
    helpBtn.type = "button";
    helpBtn.className = "wizard-help-btn";
    helpBtn.setAttribute("aria-label", "Пояснение");
    helpBtn.textContent = "?";
    helpBtn.addEventListener("click", () => {
      showScrollableHelpModal(meta.helpModal.title, meta.helpModal.body);
    });
    card.appendChild(helpBtn);
  }
  return card;
}

function appendToBody(card, node) {
  card._body.appendChild(node);
}

const STORAGE_KEYS = [
  "thought_entries",
  "exposure_entries",
  "act_issued_ids",
  "act_opened_history",
  "act_daily_card",
  "visit_streak",
];
const IDB_DB_NAME = "cbtDiaryDB";
const IDB_STORE_NAME = "kv";
const IDB_VERSION = 1;
const memoryStore = {
  thought_entries: [],
  exposure_entries: [],
  act_issued_ids: [],
  act_opened_history: [],
  act_daily_card: [],
  visit_streak: [],
};

function cloneArray(value) {
  return JSON.parse(JSON.stringify(Array.isArray(value) ? value : []));
}

function bootstrapMemoryStoreFromLocalStorage() {
  STORAGE_KEYS.forEach((key) => {
    try {
      const parsed = JSON.parse(localStorage.getItem(key) || "[]");
      memoryStore[key] = Array.isArray(parsed) ? parsed : [];
    } catch {
      memoryStore[key] = [];
    }
  });
}

function openDiaryDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(IDB_DB_NAME, IDB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(IDB_STORE_NAME)) {
        db.createObjectStore(IDB_STORE_NAME, { keyPath: "key" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function idbGet(db, key) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(IDB_STORE_NAME, "readonly");
    const store = tx.objectStore(IDB_STORE_NAME);
    const req = store.get(key);
    req.onsuccess = () => resolve(req.result ? req.result.value : null);
    req.onerror = () => reject(req.error);
  });
}

function idbSet(db, key, value) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(IDB_STORE_NAME, "readwrite");
    const store = tx.objectStore(IDB_STORE_NAME);
    store.put({ key, value });
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

let diaryDbPromise = null;
function getDiaryDb() {
  if (!diaryDbPromise) diaryDbPromise = openDiaryDb();
  return diaryDbPromise;
}

async function initIndexedDbStorage() {
  try {
    const db = await getDiaryDb();
    for (const key of STORAGE_KEYS) {
      const idbValue = await idbGet(db, key);
      if (Array.isArray(idbValue)) {
        memoryStore[key] = idbValue;
      } else {
        await idbSet(db, key, memoryStore[key]);
      }
    }
    if (state.page === "thoughtsHistory") renderThoughtHistory();
    if (state.page === "exposure") renderExposureHistory();
  } catch {
    // Если IndexedDB недоступен, продолжаем работать на in-memory/localStorage bootstrap.
  }
}

function persistKey(key) {
  getDiaryDb()
    .then((db) => idbSet(db, key, memoryStore[key]))
    .catch(() => {});
}

function setLocalArray(key, value) {
  memoryStore[key] = cloneArray(value);
  persistKey(key);
}

bootstrapMemoryStoreFromLocalStorage();
initIndexedDbStorage();

function saveLocal(key, value) {
  const old = loadLocal(key);
  old.push(value);
  setLocalArray(key, old);
}

function loadLocal(key) {
  return cloneArray(memoryStore[key] || []);
}

function getLocalDateKey() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function getVisitStreakFromStore() {
  const arr = loadLocal("visit_streak");
  const row = arr[0];
  if (!row || typeof row !== "object") return { lastDateKey: "", streak: 0 };
  return { lastDateKey: String(row.lastDateKey || ""), streak: Math.max(0, parseInt(String(row.streak), 10) || 0) };
}

function saveVisitStreak(lastDateKey, streak) {
  setLocalArray("visit_streak", [{ lastDateKey, streak }]);
}

function updateVisitStreak() {
  const today = getLocalDateKey();
  let { lastDateKey, streak } = getVisitStreakFromStore();
  if (lastDateKey === today) {
    return streak;
  }
  const y = new Date();
  y.setDate(y.getDate() - 1);
  const yesterdayKey = `${y.getFullYear()}-${String(y.getMonth() + 1).padStart(2, "0")}-${String(y.getDate()).padStart(2, "0")}`;
  if (!lastDateKey) {
    streak = 1;
  } else if (lastDateKey === yesterdayKey) {
    streak += 1;
  } else {
    streak = 1;
  }
  saveVisitStreak(today, streak);
  return streak;
}

function formatSavedAt(value) {
  if (!value) return "без даты";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "без даты";
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function askDeleteConfirm(message = "Вы уверены, что хотите удалить эту запись?") {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "confirm-overlay";
    const box = document.createElement("div");
    box.className = "confirm-box glass";
    const text = document.createElement("p");
    text.className = "confirm-text";
    text.textContent = message;
    const actions = document.createElement("div");
    actions.className = "confirm-actions";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "ghost-btn";
    cancel.textContent = "Отмена";
    const ok = document.createElement("button");
    ok.type = "button";
    ok.className = "ghost-btn danger-btn";
    ok.textContent = "Удалить";

    const close = (result) => {
      overlay.remove();
      resolve(result);
    };
    cancel.addEventListener("click", () => close(false));
    ok.addEventListener("click", () => close(true));
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) close(false);
    });

    actions.append(cancel, ok);
    box.append(text, actions);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
  });
}

function showScrollableHelpModal(title, bodyText) {
  const overlay = document.createElement("div");
  overlay.className = "confirm-overlay";
  const box = document.createElement("div");
  box.className = "help-modal-box glass";
  const h = document.createElement("h2");
  h.className = "help-modal-title";
  h.textContent = title;
  const body = document.createElement("div");
  body.className = "help-modal-body";
  body.textContent = bodyText;
  const actions = document.createElement("div");
  actions.className = "confirm-actions";
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "ghost-btn";
  closeBtn.textContent = "Закрыть";
  const close = () => overlay.remove();
  closeBtn.addEventListener("click", close);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close();
  });
  actions.appendChild(closeBtn);
  box.append(h, body, actions);
  overlay.appendChild(box);
  document.body.appendChild(overlay);
}

function getAutomaticThoughtHelp() {
  const title = "Как распознать автоматические мысли: инструкция для пациента";
  const fromWindow =
    typeof window !== "undefined" && window.AUTOMATIC_THOUGHT_HELP_TITLE && window.AUTOMATIC_THOUGHT_HELP_BODY
      ? {
          title: window.AUTOMATIC_THOUGHT_HELP_TITLE,
          body: window.AUTOMATIC_THOUGHT_HELP_BODY,
        }
      : null;
  if (fromWindow) return fromWindow;
  return {
    title,
    body:
      "Когда мы начинаем вести дневник мыслей, многие сначала путают автоматические мысли с размышлениями или фактами. Полный текст инструкции загружается из файла automatic-thought-help.js — проверьте, что он подключён в index.html перед app.js.",
  };
}

function makeId() {
  return `id-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function csvCell(v) {
  const t = String(v ?? "").replaceAll("\"", "\"\"");
  return `"${t}"`;
}

function emotionsToString(list) {
  return (list || [])
    .map((e) => `${e.emotion || "—"} (${e.intensity ?? "—"})`)
    .join(", ");
}

function alternativesToString(list) {
  return (list || [])
    .map((a) => `${a.thought || "—"} (${a.confidence ?? "—"})`)
    .join(" | ");
}

function ensureThoughtEntryIds() {
  const entries = loadLocal("thought_entries");
  let changed = false;
  entries.forEach((entry) => {
    if (!entry.id) {
      entry.id = makeId();
      changed = true;
    }
  });
  if (changed) setLocalArray("thought_entries", entries);
  return entries;
}

function deleteThoughtEntryById(id) {
  const entries = loadLocal("thought_entries");
  const next = entries.filter((entry) => entry.id !== id);
  setLocalArray("thought_entries", next);
}

function downloadThoughtEntryExcel(entry) {
  const headers = [
    "Дата",
    "Время",
    "Ситуация",
    "Эмоции до",
    "Автоматическая мысль",
    "Действие",
    "Доводы за",
    "Доводы против",
    "Альтернативная мысль",
    "Эмоции после",
    "Комментарий",
  ];
  const d = entry.savedAt ? new Date(entry.savedAt) : null;
  const datePart = d && !Number.isNaN(d.getTime()) ? d.toLocaleDateString("ru-RU") : "";
  const timePart = d && !Number.isNaN(d.getTime()) ? d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) : "";
  const firstAlt = entry.alternativeThoughts?.[0]?.thought || "";
  const row = [
    datePart,
    timePart,
    entry.situation || "",
    emotionsToString(entry.emotionsBefore),
    entry.automaticThought || "",
    entry.action || "",
    entry.evidenceFor || "",
    entry.evidenceAgainst || "",
    firstAlt || alternativesToString(entry.alternativeThoughts),
    emotionsToString(entry.emotionsAfter),
    entry.noteToFutureSelf || "",
  ];
  const csv = `${headers.map(csvCell).join(";")}\n${row.map(csvCell).join(";")}`;
  const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  const safe = (entry.situation || "zapis").toLowerCase().replaceAll(/[^a-zа-я0-9]+/gi, "_").replaceAll(/^_+|_+$/g, "");
  link.href = URL.createObjectURL(blob);
  link.download = `${safe || "zapis"}_${datePart || "date"}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
}

function getThoughtEntriesByRange(range, fromDate, toDate) {
  const entries = ensureThoughtEntryIds();
  if (range === "all") return entries;
  const now = new Date();
  let from = null;
  let to = null;
  if (range === "week") {
    from = new Date(now);
    from.setDate(from.getDate() - 7);
    to = now;
  } else if (range === "month") {
    from = new Date(now);
    from.setMonth(from.getMonth() - 1);
    to = now;
  } else if (range === "custom") {
    if (!fromDate || !toDate) return [];
    from = new Date(`${fromDate}T00:00:00`);
    to = new Date(`${toDate}T23:59:59`);
  }
  return entries.filter((entry) => {
    if (!entry.savedAt) return false;
    const d = new Date(entry.savedAt);
    if (Number.isNaN(d.getTime())) return false;
    return d >= from && d <= to;
  });
}

function buildThoughtRows(entries) {
  return entries.map((entry) => {
    const d = entry.savedAt ? new Date(entry.savedAt) : null;
    const datePart = d && !Number.isNaN(d.getTime()) ? d.toLocaleDateString("ru-RU") : "";
    const timePart = d && !Number.isNaN(d.getTime()) ? d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) : "";
    const firstAlt = entry.alternativeThoughts?.[0]?.thought || "";
    return [
      datePart,
      timePart,
      entry.situation || "",
      emotionsToString(entry.emotionsBefore),
      entry.automaticThought || "",
      entry.action || "",
      entry.evidenceFor || "",
      entry.evidenceAgainst || "",
      firstAlt || alternativesToString(entry.alternativeThoughts),
      emotionsToString(entry.emotionsAfter),
      entry.noteToFutureSelf || "",
    ];
  });
}

function downloadThoughtEntriesExcel(entries, filenameBase = "zapisi") {
  const headers = [
    "Дата",
    "Время",
    "Ситуация",
    "Эмоции до",
    "Автоматическая мысль",
    "Действие",
    "Доводы за",
    "Доводы против",
    "Альтернативная мысль",
    "Эмоции после",
    "Комментарий",
  ];
  const rows = buildThoughtRows(entries);
  const csv = [headers, ...rows].map((row) => row.map(csvCell).join(";")).join("\n");
  const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${filenameBase}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
}

function getSelectedRange(name) {
  const checked = document.querySelector(`input[name="${name}"]:checked`);
  return checked ? checked.value : "week";
}

function updateRangeCustomVisibility(name, customId) {
  const range = getSelectedRange(name);
  const custom = document.getElementById(customId);
  if (!custom) return;
  custom.classList.toggle("hidden", range !== "custom");
}

function renderThoughtHistory() {
  const root = document.getElementById("thoughts-history-list");
  const searchInput = document.getElementById("thoughts-history-search");
  const filterSituation = document.getElementById("filter-situation");
  const filterAutomaticThought = document.getElementById("filter-automatic-thought");
  const filterEmotions = document.getElementById("filter-emotions");
  if (!root || !searchInput || !filterSituation || !filterAutomaticThought || !filterEmotions) return;
  const entries = ensureThoughtEntryIds();
  const query = searchInput.value.trim().toLowerCase();
  const selectedFields = {
    situation: filterSituation.checked,
    automaticThought: filterAutomaticThought.checked,
    emotions: filterEmotions.checked,
  };
  const hasAnyField = selectedFields.situation || selectedFields.automaticThought || selectedFields.emotions;
  const filtered = entries
    .slice()
    .reverse()
    .filter((entry) => {
      if (!hasAnyField) return false;
      if (!query) return true;
      const fields = [];
      if (selectedFields.situation) fields.push(entry.situation || "");
      if (selectedFields.automaticThought) fields.push(entry.automaticThought || "");
      if (selectedFields.emotions) {
        const before = (entry.emotionsBefore || []).map((e) => e.emotion).join(" ");
        const after = (entry.emotionsAfter || []).map((e) => e.emotion).join(" ");
        fields.push(before, after);
      }
      const hay = fields.join(" ").toLowerCase();
      return hay.includes(query);
    });

  root.innerHTML = "";
  if (!filtered.length) {
    const empty = document.createElement("p");
    empty.className = "hint";
    if (!hasAnyField) {
      empty.textContent = "Выберите хотя бы одно поле поиска.";
    } else {
      empty.textContent = entries.length
        ? "По вашему запросу ничего не найдено."
        : "Пока нет сохраненных записей.";
    }
    root.appendChild(empty);
    return;
  }
  filtered.forEach((entry) => {
    const item = document.createElement("article");
    item.className = "saved-item";
    const row = document.createElement("div");
    row.className = "saved-item-row";
    const openBtn = document.createElement("button");
    openBtn.type = "button";
    openBtn.className = "saved-item-btn";
    const situation = (entry.situation || "Без описания ситуации").trim();
    const thought = (entry.automaticThought || "—").trim();
    openBtn.innerHTML = `
      <div class="saved-item-top">
        <strong>${escapeHtml(situation)}</strong>
        <span>${formatSavedAt(entry.savedAt)}</span>
      </div>
      <p><b>Автоматическая мысль:</b> ${escapeHtml(thought)}</p>
    `;
    openBtn.addEventListener("click", () => {
      state.selectedThoughtEntry = entry;
      renderThoughtRecordDetail();
      showPage("thoughtRecord");
    });

    const actions = document.createElement("div");
    actions.className = "saved-item-actions";
    const downloadBtn = document.createElement("button");
    downloadBtn.type = "button";
    downloadBtn.className = "saved-mini-btn";
    downloadBtn.title = "Скачать Excel";
    downloadBtn.textContent = "DL";
    downloadBtn.addEventListener("click", () => downloadThoughtEntryExcel(entry));
    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "saved-mini-btn danger";
    deleteBtn.title = "Удалить запись";
    deleteBtn.textContent = "X";
    deleteBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!(await askDeleteConfirm())) return;
      deleteThoughtEntryById(entry.id);
      if (state.selectedThoughtEntry?.id === entry.id) state.selectedThoughtEntry = null;
      renderThoughtHistory();
    });
    actions.append(downloadBtn, deleteBtn);
    row.append(openBtn, actions);
    item.appendChild(row);
    root.appendChild(item);
  });
}

function renderThoughtRecordDetail() {
  const root = document.getElementById("thought-record-detail");
  if (!root) return;
  const entry = state.selectedThoughtEntry;
  root.innerHTML = "";
  if (!entry) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = "Запись не выбрана.";
    root.appendChild(empty);
    return;
  }
  const firstAlt = entry.alternativeThoughts?.[0]?.thought || "—";
  const summary = document.createElement("div");
  summary.className = "summary";
  summary.innerHTML = `Готовая запись

• Дата: ${formatSavedAt(entry.savedAt)}
• Ситуация: ${escapeHtml(entry.situation || "—")}
• Автоматическая мысль: ${escapeHtml(entry.automaticThought || "—")}
• Альтернативная мысль: ${escapeHtml(firstAlt)}
• Заметка: ${escapeHtml(entry.noteToFutureSelf || "—")}`;
  root.appendChild(summary);
  const chart = buildEmotionChart(entry.emotionsBefore || [], entry.emotionsAfter || []);
  if (chart) root.appendChild(chart);
}

function ensureExposureEntryIds() {
  const entries = loadLocal("exposure_entries");
  let changed = false;
  entries.forEach((entry) => {
    if (!entry.id) {
      entry.id = makeId();
      changed = true;
    }
  });
  if (changed) setLocalArray("exposure_entries", entries);
  return entries;
}

function deleteExposureEntryById(id) {
  const entries = ensureExposureEntryIds();
  const next = entries.filter((e) => e.id !== id);
  setLocalArray("exposure_entries", next);
}

function formatDateDdMmYyyy(value) {
  if (!value) return "";
  const [y, m, d] = String(value).split("-");
  if (!y || !m || !d) return String(value);
  return `${d}/${m}/${y.slice(-2)}`;
}

function formatEventDateTime(eventDate, eventTime) {
  const datePart = formatDateDdMmYyyy(eventDate || "");
  if (!datePart) return "не указано";
  return eventTime ? `${datePart} ${eventTime}` : datePart;
}

function getExposureEventEndMs(entry) {
  if (!entry?.eventDate || !entry?.eventTime) return null;
  const start = new Date(`${entry.eventDate}T${entry.eventTime}:00`);
  if (Number.isNaN(start.getTime())) return null;
  const duration = Number(entry.durationMinutes || 0);
  return start.getTime() + Math.max(0, duration) * 60 * 1000;
}

function getExposureStatus(entry) {
  if (entry?.realityReview?.completedAt) return "completed";
  const endMs = getExposureEventEndMs(entry);
  if (endMs === null) return "expected";
  return Date.now() >= endMs ? "past" : "expected";
}

function getExposureStatusLabel(status) {
  if (status === "completed") return "Завершена";
  if (status === "past") return "Прошедшая";
  return "Ожидаемая";
}

function updateExposureAlerts() {
  const historyBtn = document.getElementById("open-exposure-history-btn");
  if (!historyBtn) return;
  const entries = ensureExposureEntryIds();
  const hasPendingReview = entries.some((entry) => getExposureStatus(entry) === "past");
  historyBtn.classList.toggle("has-alert-dot", hasPendingReview);
}

const ACT_GROUPS = [
  { id: 1, name: "Деффузия" },
  { id: 2, name: "Осознанность" },
  { id: 3, name: "Принятие" },
  { id: 4, name: "Наблюдающее Я" },
  { id: 5, name: "Ценностно-ориентированные действия" },
];

function buildActCards() {
  const byGroup = {
    1: [
      ["Кинотеатр", "Представьте, что ваши мысли — это фильм на экране в кинотеатре. Кадры сменяются: счастливые, грустные, горькие, светлые. А вы — зритель в зале. Фильм идёт сам по себе. Вы можете просто смотреть."],
      ["Ты — не их содержание", "У вас есть мысли и чувства. Вы переживаете их в эту минуту, переживали вчера, будете переживать завтра. Но вы — не они. Почувствуйте разницу: вы — это тот, кто переживает. А переживания приходят и уходят."],
      ["Наблюдатель в голове", "Вы — не ваши мысли, не чувства, не ощущения и не воспоминания. Остановитесь. Просто заметьте, какие чувства сейчас внутри. Вы можете отстраниться от них и заметить сам момент их появления в уме."],
      ["Положи это на стол", "Представьте, что ваше самое болезненное убеждение о себе можно положить на стол. Просто вообразите это. Вы — не эта карточка. И точно так же вы — не эта мысль. Она существует отдельно от вас."],
      ["Владелец, а не часть", "Переведите внимание на левую ступню. Пошевелите пальцами. Какие ощущения: тепло, холод, сухость, зуд? Вы направили внимание на ногу — точно так же вы можете направить его на ум. У вас есть нога, но вы — не нога. У вас есть ум, но вы — не ум."],
      ["Пассажир в поезде", "Представьте, что ваши переживания и тело — это вагон поезда, а вы — пассажир, который смотрит в окно. Вы внутри, но вы — не сам поезд. Мир и ощущения проходят мимо, вы просто наблюдаете."],
      ["Внутренний критик", "Заметьте, какие оценки и суждения управляют вашими действиями. Представьте, что это голос строгого учителя. Куда он вас ведёт? Что вы обычно делаете, когда подчиняетесь этому голосу?"],
      ["Телевизор в комнате", "Представьте, что в углу комнаты работает телевизор. Он транслирует мысли, оценки, чувства, ощущения, воспоминания. Просто заметьте, что идёт по телевизору. Вы можете смотреть или не смотреть. Вы — не телевизор."],
      ["Парадокс", "Скажите вслух: «Я не могу поднять руки» — и одновременно поднимите их вверх. Ваш ум не всегда управляет телом."],
      ["Мокрое мыло", "Возьмите в руку кусок мокрого мыла и крепко сожмите. Ваши трудные мысли и ощущения похожи на это мыло: чем сильнее вы его сжимаете, тем быстрее оно выскальзывает. Держите его в открытой ладони — легко."],
      ["Мысль на ладони", "Представьте, что самая назойливая мысль лежит у вас на раскрытой ладони. Рассмотрите её как предмет. Какого она цвета? Формы? Веса? Вы держите её. Вы — не она."],
      ["Радио «Тревога»", "Включите в голове радио, которое транслирует ваши страхи. А теперь медленно поверните ручку громкости вниз. Не выключайте. Пусть играет тихо-тихо, где-то на фоне."],
      ["Комментатор матча", "Представьте, что ваш внутренний критик — это спортивный комментатор, который говорит без остановки. Поблагодарите его за работу. А сами продолжайте играть."],
    ],
    2: [
      ["5-4-3-2-1", "Назовите 5 объектов, 4 ощущения, 3 звука, 2 запаха, 1 вкус."],
      ["Три медленных выдоха", "Сделайте 3 длинных выдоха, замечая плечи, челюсть и живот."],
      ["Скан стоп", "30 секунд просканируйте тело сверху вниз без оценки."],
      ["Стопы на полу", "Почувствуйте опору стоп 45 секунд, переносите вес влево-вправо."],
      ["Окно внимания", "30 секунд слушайте только звуки, затем только ощущения в теле."],
      ["Микропаузa", "На 1 минуту остановитесь и наблюдайте дыхание без попыток менять его."],
      ["Контакт с руками", "Сожмите и разожмите кулаки 10 раз, отслеживая ощущения."],
      ["Ориентирование", "Медленно осмотрите пространство и найдите 5 безопасных деталей."],
      ["Дыхание 4-6", "Вдох 4 счета, выдох 6 счетов, 1-2 минуты."],
      ["Пауза перед реакцией", "Сделайте один вдох-выдох прежде чем отвечать/действовать."],
      ["Текущая минута", "Спросите себя: «Что я вижу, слышу и чувствую прямо сейчас?»"],
      ["Чай/вода осознанно", "Сделайте 5 осознанных глотков, отмечая температуру и вкус."],
    ],
    3: [
      ["Дать место", "Назовите эмоцию и скажите: «Я могу дать ей место на 1 минуту»."],
      ["Мягкое расширение", "На вдохе отмечайте зону напряжения, на выдохе расширяйте пространство вокруг неё."],
      ["Разрешение быть", "Повторите: «Мне не нравится это чувство, но я могу его выдержать»."],
      ["Волна дискомфорта", "Наблюдайте, как эмоция растет и спадает, как волна."],
      ["Без борьбы", "Заметьте 3 способа, которыми вы сопротивляетесь чувству, и отпустите один."],
      ["Теплая ладонь", "Положите ладонь на грудь/живот и дышите 60 секунд."],
      ["Словарь эмоции", "Опишите эмоцию 3 словами без оценки («жар», «сжатие», «дрожь»)."],
      ["Контейнер", "Представьте, что внутри вас есть пространство, способное удержать это чувство."],
      ["Нормализация", "Скажите: «Это человеческая реакция, не ошибка»."],
      ["Пауза и согласие", "На 1 минуту прекращайте «чинить» себя, просто присутствуйте с опытом."],
      ["Таймер дискомфорта", "Поставьте таймер на 90 сек и наблюдайте чувство до сигнала."],
      ["Шаг вместе с чувством", "Выберите маленькое действие и сделайте его, не дожидаясь, пока станет легко."],
    ],
    4: [
      ["Я замечаю", "60 секунд: «Я замечаю мысль... Я замечаю эмоцию... Я замечаю импульс...»"],
      ["Небо и погода", "Вы — небо, переживания — погода. Останьтесь «небом» 1 минуту."],
      ["Киноэкран", "Смотрите на внутренний опыт как на фильм на экране."],
      ["Камера наблюдателя", "Опишите ситуацию от третьего лица без оценок."],
      ["Имя наблюдателя", "Назовите позицию наблюдателя (например, «спокойный свидетель») и удерживайте её 1 минуту."],
      ["Точка обзора", "Представьте, что смотрите на себя с балкона — что видите нейтрально?"],
      ["Мета-фраза", "Повторите: «Я больше, чем эта эмоция/мысль» 5 раз."],
      ["Дистанция 1 метр", "Вообразите, что опыт находится в метре перед вами."],
      ["Фон и фигура", "Заметьте: мысли — фигура, осознавание — фон."],
      ["Запись наблюдений", "Запишите 3 факта о внутреннем опыте без интерпретаций."],
      ["Смена ракурса", "Сначала опишите от «я внутри», потом от «я-наблюдателя»."],
      ["Тишина 45 секунд", "45 секунд просто наблюдайте изменения в теле/мыслях."],
    ],
    5: [
      ["Шаг на 2 минуты", "Выберите действие по ценности, которое займет 2 минуты, и сделайте его."],
      ["Ценность дня", "Назовите ценность на сегодня и одно конкретное действие под неё."],
      ["Мини-возврат к жизни", "Сделайте один маленький шаг к обычной жизни (звонок, душ, 5 строк работы)."],
      ["Контакт вместо избегания", "Сделайте то, что откладывали, хотя бы 3 минуты."],
      ["Честный разговор", "Скажите одну важную фразу, которую избегали, в уважительной форме."],
      ["Забота о теле", "Один акт заботы: вода, еда, прогулка 5-10 минут, сон-гигиена."],
      ["Ценность в отношениях", "Напишите/сделайте 1 действие «быть тёплым и присутствующим»."],
      ["Рабочий микрошаг", "Откройте задачу и выполните самый маленький подшаг."],
      ["План на кризис", "Запишите: если накроет, то я сделаю шаг A, затем B."],
      ["Смелый шаг", "Сделайте действие, которое приближает к целям, несмотря на тревогу."],
      ["След в календаре", "Запланируйте на конкретное время действие по ценности и поставьте напоминание."],
      ["Итог дня", "Вечером запишите 1 шаг по ценности, который вы сделали сегодня."],
    ],
  };

  const cards = [];
  ACT_GROUPS.forEach((g) => {
    byGroup[g.id].forEach((item, idx) => {
      cards.push({
        id: `act-${g.id}-${idx + 1}`,
        groupId: g.id,
        groupName: g.name,
        title: item[0],
        task: item[1],
      });
    });
  });
  return cards;
}

const ACT_CARDS = buildActCards();
const DEFUSION_BACK_IMAGES_IN_ORDER = [
  "./image/Card/Наблюдатель в голове.png",
  "./image/Card/Парадокс.png",
  "./image/Card/Пассажир в поезде.png",
  "./image/Card/Положи это на стол.png",
  "./image/Card/Радио «Тревога».png",
  "./image/Card/Телевизор в комнате.png",
  "./image/Card/Ты — не их содержание.png",
  "./image/Card/Владелец, а не часть.png",
  "./image/Card/Внутренний критик.png",
  "./image/Card/кинотеатр.png",
  "./image/Card/Комментатор матча.png",
  "./image/Card/Мокрое мыло.png",
  "./image/Card/Мысль на ладони.png",
];
const DEFUSION_BACK_IMAGES_BY_TITLE = {
  "Наблюдатель в голове": "./image/Card/Наблюдатель в голове.png",
  "Парадокс": "./image/Card/Парадокс.png",
  "Пассажир в поезде": "./image/Card/Пассажир в поезде.png",
  "Положи это на стол": "./image/Card/Положи это на стол.png",
  "Радио «Тревога»": "./image/Card/Радио «Тревога».png",
  "Телевизор в комнате": "./image/Card/Телевизор в комнате.png",
  "Ты — не их содержание": "./image/Card/Ты — не их содержание.png",
  "Владелец, а не часть": "./image/Card/Владелец, а не часть.png",
  "Внутренний критик": "./image/Card/Внутренний критик.png",
  "Кинотеатр": "./image/Card/кинотеатр.png",
  "Комментатор матча": "./image/Card/Комментатор матча.png",
  "Мокрое мыло": "./image/Card/Мокрое мыло.png",
  "Мысль на ладони": "./image/Card/Мысль на ладони.png",
};

function getActBackImage(card) {
  if (!card || card.groupId !== 1) return "";
  if (DEFUSION_BACK_IMAGES_BY_TITLE[card.title]) return DEFUSION_BACK_IMAGES_BY_TITLE[card.title];
  const idParts = String(card.id || "").split("-");
  const idx = Number(idParts[2]) - 1;
  if (!Number.isNaN(idx) && idx >= 0 && idx < DEFUSION_BACK_IMAGES_IN_ORDER.length) {
    return DEFUSION_BACK_IMAGES_IN_ORDER[idx];
  }
  return "";
}

function buildAchievementsList() {
  const thoughts = loadLocal("thought_entries").length;
  const exposure = loadLocal("exposure_entries").length;
  const issuedSet = getActIssuedIds();
  const totalAct = ACT_CARDS.length;
  const items = [];

  [
    { n: 1, title: "Дневник мыслей: первая запись", desc: "Сделайте 1 запись в дневнике мыслей" },
    { n: 10, title: "Дневник мыслей: 10 записей", desc: "Сделайте 10 записей в дневнике мыслей" },
    { n: 50, title: "Дневник мыслей: 50 записей", desc: "Сделайте 50 записей в дневнике мыслей" },
  ].forEach(({ n, title, desc }) => {
    items.push({ title, desc, unlocked: thoughts >= n });
  });

  [
    { n: 1, title: "Дневник экспозиции: первая запись", desc: "Сделайте 1 запись в дневнике экспозиции" },
    { n: 10, title: "Дневник экспозиции: 10 записей", desc: "Сделайте 10 записей в дневнике экспозиции" },
    { n: 50, title: "Дневник экспозиции: 50 записей", desc: "Сделайте 50 записей в дневнике экспозиции" },
  ].forEach(({ n, title, desc }) => {
    items.push({ title, desc, unlocked: exposure >= n });
  });

  const allCardsUnlocked = totalAct > 0 && ACT_CARDS.every((c) => issuedSet.has(c.id));
  items.push({
    title: "АКТ: все карточки",
    desc: `Откройте все ${totalAct} карточек`,
    unlocked: allCardsUnlocked,
  });

  ACT_GROUPS.forEach((g) => {
    const groupCards = ACT_CARDS.filter((c) => c.groupId === g.id);
    const total = groupCards.length;
    const complete = total > 0 && groupCards.every((c) => issuedSet.has(c.id));
    items.push({
      title: `АКТ: группа «${g.name}»`,
      desc: total ? `Откройте все ${total} карточек этой группы` : "Нет карточек в группе",
      unlocked: complete,
    });
  });

  items.sort((a, b) => {
    const au = !!a.unlocked;
    const bu = !!b.unlocked;
    if (au === bu) return 0;
    return au ? -1 : 1;
  });
  return items;
}

function getAchievementsProgress() {
  const items = buildAchievementsList();
  return { unlocked: items.filter((i) => i.unlocked).length, total: items.length };
}

function renderAchievements() {
  const root = document.getElementById("achievements-root");
  if (!root) return;
  const items = buildAchievementsList();
  const unlockedCount = items.filter((i) => i.unlocked).length;
  const unlockedItems = items.filter((i) => i.unlocked);
  const lockedItems = items.filter((i) => !i.unlocked);
  const cardHtml = (i) => `
        <article class="saved-item achievement-card${i.unlocked ? " achievement-card--unlocked" : ""}">
          <p class="achievement-card-title">${escapeHtml(i.title)}</p>
          <p class="hint">${escapeHtml(i.desc)}</p>
          <p class="achievement-card-state">${i.unlocked ? "Получено" : "Закрыто"}</p>
        </article>`;
  root.innerHTML = `
    <p class="hint">Открыто: ${unlockedCount} / ${items.length}</p>
    <div class="achievements-grid">
      ${unlockedItems.map(cardHtml).join("")}
      ${lockedItems.map(cardHtml).join("")}
    </div>
  `;
}

const ACT_GROUP_COVERS = {
  1: "./image/1.png",
  2: "./image/2.png",
  3: "./image/3.png",
  4: "./image/4.png",
  5: "./image/5.png",
};

function getActIssuedIds() {
  return new Set(loadLocal("act_issued_ids"));
}

function getActCardById(id) {
  return ACT_CARDS.find((c) => c.id === id) || null;
}

function getTodayDateKey() {
  return new Date().toISOString().slice(0, 10);
}

function getDailyActCardEntry() {
  const arr = loadLocal("act_daily_card");
  return Array.isArray(arr) && arr.length ? arr[0] : null;
}

function setDailyActCardEntry(entry) {
  setLocalArray("act_daily_card", entry ? [entry] : []);
}

function renderActHub() {
  const progress = document.getElementById("act-progress");
  const lastCard = document.getElementById("act-last-card");
  if (!progress || !lastCard) return;
  const issued = getActIssuedIds();
  const remaining = ACT_CARDS.length - issued.size;
  const byGroups = ACT_GROUPS.map((g) => {
    const total = ACT_CARDS.filter((c) => c.groupId === g.id).length;
    const got = ACT_CARDS.filter((c) => c.groupId === g.id && issued.has(c.id)).length;
    return { ...g, total, got };
  });

  progress.innerHTML = "";
  const stat = document.createElement("div");
  stat.className = "saved-item";
  stat.innerHTML = `<p><b>Открыто:</b> ${issued.size} / ${ACT_CARDS.length}</p>`;
  progress.appendChild(stat);

  byGroups.forEach((g) => {
    const percent = g.total ? Math.round((g.got / g.total) * 100) : 0;
    const row = document.createElement("button");
    row.type = "button";
    row.className = "saved-item act-progress-item";
    row.innerHTML = `
      <div class="act-progress-row">
        <div class="act-progress-top">
          <span class="act-progress-label">${escapeHtml(g.name)}</span>
          <span class="act-progress-count">${g.got} / ${g.total}</span>
        </div>
        <div class="act-progress-bar">
          <div class="act-progress-fill" style="width:${percent}%"></div>
        </div>
      </div>
    `;
    row.addEventListener("click", () => {
      state.selectedActGroupId = g.id;
      showPage("actCollection");
    });
    progress.appendChild(row);
  });

  const history = loadLocal("act_opened_history");
  const daily = getDailyActCardEntry();
  if (history.length) {
    const lastId = history[history.length - 1];
    const card = getActCardById(lastId);
    if (card) {
      lastCard.classList.remove("hidden");
      lastCard.innerHTML = `<b>Карточка дня:</b> ${escapeHtml(card.groupName)} · ${escapeHtml(card.title)}\n${escapeHtml(card.task)}`;
    }
  } else {
    lastCard.classList.add("hidden");
    lastCard.textContent = "";
  }
  const btn = document.getElementById("open-act-case-btn");
  const extraBtn = document.getElementById("open-act-case-extra-btn");
  if (btn) {
    const isTodayIssued = daily && daily.dateKey === getTodayDateKey();
    btn.disabled = !!isTodayIssued;
    btn.textContent = isTodayIssued ? "Карточка дня уже получена" : "Получить карточку";
    if (extraBtn) {
      extraBtn.classList.toggle("hidden", !isTodayIssued);
      extraBtn.disabled = false;
    }
  }
}

function renderActCollection(groupId) {
  const title = document.getElementById("act-collection-title");
  const grid = document.getElementById("act-collection-grid");
  if (!title || !grid) return;
  const group = ACT_GROUPS.find((g) => g.id === groupId);
  const cards = ACT_CARDS.filter((c) => c.groupId === groupId);
  const issued = getActIssuedIds();
  title.textContent = group ? `Коллекция: ${group.name}` : "Коллекция";
  grid.innerHTML = "";
  cards.forEach((card, idx) => {
    const opened = issued.has(card.id);
    const tile = document.createElement("article");
    tile.className = `act-collection-tile${opened ? " opened" : " locked"}`;
    tile.innerHTML = opened
      ? `<div class="act-collection-num">#${idx + 1}</div><h4>${escapeHtml(card.title)}</h4><p>${escapeHtml(card.task)}</p>`
      : `<div class="act-collection-num">#${idx + 1}</div><h4>Закрыто</h4><p>Откройте карточку в кейсе</p>`;
    grid.appendChild(tile);
  });
}

function openActCaseAnimation(card, pool) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "confirm-overlay";
    const box = document.createElement("div");
    box.className = "case-open-box glass";
    const title = document.createElement("h3");
    title.textContent = "Открытие кейса...";
    const reel = document.createElement("div");
    reel.className = "case-reel";
    const cover = document.createElement("img");
    cover.className = "case-reel-cover";
    cover.alt = "Обложка карточки";
    const label = document.createElement("div");
    label.className = "case-reel-line";
    reel.append(cover, label);
    const info = document.createElement("p");
    info.className = "hint";
    info.textContent = "Ищем обложку...";
    const confirmBtn = document.createElement("button");
    confirmBtn.type = "button";
    confirmBtn.className = "primary-btn hidden";
    confirmBtn.textContent = "Забрать карточку";
    box.append(title, reel, info, confirmBtn);
    overlay.appendChild(box);
    document.body.appendChild(overlay);

    const groupsPool = ACT_GROUPS.slice();
    const sequence = [];
    for (let i = 0; i < 24; i++) {
      sequence.push(groupsPool[Math.floor(Math.random() * groupsPool.length)].id);
    }
    sequence.push(card.groupId);
    let idx = 0;
    let rolledDone = false;
    const renderFront = (groupId) => {
      cover.src = ACT_GROUP_COVERS[groupId] || "";
      const g = ACT_GROUPS.find((x) => x.id === groupId);
      label.textContent = g ? g.name : "АКТ карточка";
    };
    const iv = setInterval(() => {
      const current = sequence[Math.min(idx, sequence.length - 1)];
      renderFront(current);
      idx += 1;
      if (idx >= sequence.length) {
        clearInterval(iv);
        rolledDone = true;
        info.textContent = "Нажмите на обложку, чтобы перевернуть карточку.";
        reel.classList.add("case-reel--flip-ready");
      }
    }, 90);

    reel.addEventListener("click", () => {
      if (!rolledDone) return;
      if (reel.classList.contains("flipped")) return;
      reel.classList.add("flipped");
      const backImage = getActBackImage(card);
      reel.innerHTML = `
        <div class="case-card-back">
          ${
            backImage
              ? `<div class="case-card-back-media"><img class="case-card-back-image" src="${encodeURI(backImage)}" alt="${escapeHtml(card.title)}" /></div>`
              : ""
          }
          <div class="case-card-back-body">
            <div class="case-card-back-group">${escapeHtml(card.groupName)}</div>
            <div class="case-card-back-title">${escapeHtml(card.title)}</div>
            <div class="case-card-back-task">${escapeHtml(card.task)}</div>
          </div>
        </div>
      `;
      info.textContent = "Карточка открыта.";
      confirmBtn.classList.remove("hidden");
    });
    confirmBtn.addEventListener("click", () => {
      overlay.remove();
      resolve();
    });
  });
}

async function openActCase(force = false) {
  const todayKey = getTodayDateKey();
  const daily = getDailyActCardEntry();
  if (!force && daily && daily.dateKey === todayKey) {
    const currentCard = getActCardById(daily.cardId);
    if (currentCard) {
      alert(`Карточка на сегодня уже получена:\n\n${currentCard.groupName}\n${currentCard.title}\n\n${currentCard.task}`);
    } else {
      alert("Карточка на сегодня уже получена.");
    }
    return;
  }
  const issued = getActIssuedIds();
  const pool = ACT_CARDS.filter((c) => !issued.has(c.id));
  if (!pool.length) {
    alert("Все карточки уже открыты.");
    return;
  }
  // Для проверки карточек: выдаем сначала карточки группы "Деффузия", если они еще есть.
  const defusionPool = pool.filter((c) => c.groupId === 1);
  const selectionPool = defusionPool.length ? defusionPool : pool;
  const card = selectionPool[Math.floor(Math.random() * selectionPool.length)];
  await openActCaseAnimation(card, pool);
  const nextIssued = Array.from(issued);
  nextIssued.push(card.id);
  setLocalArray("act_issued_ids", nextIssued);
  const history = loadLocal("act_opened_history");
  history.push(card.id);
  setLocalArray("act_opened_history", history);
  if (!force) setDailyActCardEntry({ dateKey: todayKey, cardId: card.id });
  renderActHub();
  renderDashboard();
}

function getExposureEntriesByRange(range, fromDate, toDate) {
  const entries = ensureExposureEntryIds();
  if (range === "all") return entries;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  let from = null;
  let to = null;
  if (range === "week") {
    from = new Date(today);
    from.setDate(from.getDate() - 6);
    to = now;
  } else if (range === "month") {
    from = new Date(today);
    from.setMonth(from.getMonth() - 1);
    to = now;
  } else if (range === "custom") {
    if (fromDate) from = new Date(`${fromDate}T00:00:00`);
    if (toDate) to = new Date(`${toDate}T23:59:59`);
  }
  return entries.filter((entry) => {
    const d = new Date(entry.savedAt || entry.eventDatetime || 0);
    if (Number.isNaN(d.getTime())) return false;
    if (from && d < from) return false;
    if (to && d > to) return false;
    return true;
  });
}

function downloadExposureEntriesExcel(entries, filenameBase = "exposure_entries") {
  const header = [
    "id",
    "savedAt",
    "situationName",
    "eventDate",
    "eventTime",
    "expectations",
    "emotionsBefore",
    "durationMinutes",
    "manualProcessing",
  ];
  const lines = [header.join(",")];
  entries.forEach((entry) => {
    const expectations = (entry.expectationsData || [])
      .map((e) => `${e.text || ""} (${e.probability ?? ""}%)`)
      .join(" | ");
    const emotions = (entry.emotionsBefore || [])
      .map((e) => `${e.emotion || ""} (${e.intensity ?? ""}%)`)
      .join(" | ");
    lines.push([
      csvCell(entry.id || ""),
      csvCell(formatSavedAt(entry.savedAt)),
      csvCell(entry.situationName || ""),
      csvCell(formatDateDdMmYyyy(entry.eventDate || "")),
      csvCell(entry.eventTime || ""),
      csvCell(expectations),
      csvCell(emotions),
      csvCell(entry.durationMinutes ?? ""),
      csvCell(entry.manualProcessing ? "Да" : "Нет"),
    ].join(","));
  });
  const blob = new Blob(["\uFEFF" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${filenameBase}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function renderExposureHistory() {
  const root = document.getElementById("exposure-history-list");
  if (!root) return;
  const searchInput = document.getElementById("exposure-history-search");
  const selectedStatus = document.querySelector('input[name="exposure-status-filter"]:checked')?.value || "all";
  const entries = ensureExposureEntryIds();
  const query = String(searchInput?.value || "").trim().toLowerCase();
  const filtered = entries
    .slice()
    .reverse()
    .filter((entry) => {
      const status = getExposureStatus(entry);
      if (selectedStatus !== "all" && status !== selectedStatus) return false;
      if (!query) return true;
      const expectations = (entry.expectationsData || []).map((e) => e.text || "").join(" ");
      const review = `${entry.realityReview?.whatHappened || ""} ${entry.realityReview?.comparisonSummary || ""}`;
      const hay = `${entry.situationName || ""} ${expectations} ${review}`.toLowerCase();
      return hay.includes(query);
    });
  root.innerHTML = "";
  if (!filtered.length) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = entries.length ? "По фильтру ничего не найдено." : "Пока нет сохраненных записей.";
    root.appendChild(empty);
    return;
  }
  filtered.forEach((entry) => {
    const item = document.createElement("article");
    item.className = "saved-item";
    const row = document.createElement("div");
    row.className = "saved-item-row";
    const openBtn = document.createElement("button");
    openBtn.type = "button";
    openBtn.className = "saved-item-btn";
    const title = (entry.situationName || "Без названия").trim();
    const eventAt = formatEventDateTime(entry.eventDate, entry.eventTime);
    const status = getExposureStatus(entry);
    openBtn.innerHTML = `
      <div class="saved-item-top">
        <strong>${escapeHtml(title)}</strong>
        <span>${formatSavedAt(entry.savedAt)}</span>
      </div>
      <p><b>Когда:</b> ${escapeHtml(eventAt)}</p>
      <p><b>Статус:</b> <span class="status-badge status-badge--${status}">${getExposureStatusLabel(status)}</span>${status === "past" ? ' <span class="status-alert-dot" title="Требует проработки"></span>' : ""}</p>
    `;
    const actions = document.createElement("div");
    actions.className = "saved-item-actions";
    if (status === "past") {
      const reviewBtn = document.createElement("button");
      reviewBtn.type = "button";
      reviewBtn.className = "ghost-btn";
      reviewBtn.textContent = "Проработать";
      reviewBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        state.selectedExposureEntry = entry;
        renderExposureReview();
        showPage("exposureReview");
      });
      actions.appendChild(reviewBtn);
    }
    const downloadBtn = document.createElement("button");
    downloadBtn.type = "button";
    downloadBtn.className = "saved-mini-btn";
    downloadBtn.title = "Скачать Excel";
    downloadBtn.textContent = "DL";
    downloadBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      downloadExposureEntriesExcel([entry], `exposure_${entry.id}`);
    });
    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "saved-mini-btn danger";
    deleteBtn.title = "Удалить запись";
    deleteBtn.textContent = "X";
    deleteBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!(await askDeleteConfirm())) return;
      deleteExposureEntryById(entry.id);
      renderExposureHistory();
    });
    actions.append(downloadBtn, deleteBtn);
    row.append(openBtn, actions);
    item.appendChild(row);
    root.appendChild(item);
  });
  updateExposureAlerts();
}

function renderExposureReview() {
  const root = document.getElementById("exposure-review-root");
  const entry = state.selectedExposureEntry;
  if (!root) return;
  root.innerHTML = "";
  if (!entry) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = "Запись не выбрана.";
    root.appendChild(empty);
    return;
  }
  const expectationsText = (entry.expectationsData || [])
    .map((e, i) => `${i + 1}. ${e.text || "—"} (вероятность: ${e.probability ?? "—"}%)`)
    .join("\n");
  const emotionsText = (entry.emotionsBefore || [])
    .map((e, i) => `${i + 1}. ${e.emotion || "—"} (${e.intensity ?? "—"}%)`)
    .join("\n");
  const previous = entry.realityReview || {};
  const draft = {
    step: 1,
    whatHappened: previous.whatHappened || "",
    expectationChecks: Array.isArray(previous.expectationChecks)
      ? previous.expectationChecks
      : (entry.expectationsData || []).map((e) => ({
          text: e.text || "",
          expectedProbability: e.probability ?? null,
          happened: "not_sure",
        })),
    emotionChecks: Array.isArray(previous.emotionChecks)
      ? previous.emotionChecks
      : (entry.emotionsBefore || []).map((e) => ({
          emotion: e.emotion || "",
          expectedIntensity: e.intensity ?? null,
          happened: "no",
          actualIntensity: 0,
        })),
    comparisonSummary: previous.comparisonSummary || "",
  };

  function renderStep() {
    root.innerHTML = "";

    const summary = document.createElement("div");
    summary.className = "summary";
    summary.textContent = `Ситуация: ${entry.situationName || "—"}`;
    root.appendChild(summary);

    const badge = document.createElement("div");
    badge.className = "step-badge";
    badge.textContent = `Проработка · шаг ${draft.step} из 4`;
    root.appendChild(badge);

    const actions = document.createElement("div");
    actions.className = "wizard-actions";
    const backBtn = document.createElement("button");
    backBtn.type = "button";
    backBtn.className = "ghost-btn";
    backBtn.textContent = "Назад";
    backBtn.addEventListener("click", () => {
      draft.step = Math.max(1, draft.step - 1);
      renderStep();
    });

    if (draft.step === 1) {
      const f = createInputField(
        "1) Как всё прошло в реальности?",
        draft.whatHappened,
        "textarea",
        "Опишите подробно: что произошло по факту."
      );
      f.input.setAttribute("rows", "5");
      root.appendChild(f.wrap);
      const nextBtn = document.createElement("button");
      nextBtn.type = "button";
      nextBtn.className = "primary-btn";
      nextBtn.textContent = "Далее";
      nextBtn.addEventListener("click", () => {
        if (!f.input.value.trim()) return;
        draft.whatHappened = f.input.value.trim();
        draft.step = 2;
        renderStep();
      });
      actions.append(nextBtn);
    } else if (draft.step === 2) {
      const h = document.createElement("h3");
      h.textContent = "2) Что произошло по каждому ожиданию?";
      root.appendChild(h);
      if (!draft.expectationChecks.length) {
        const p = document.createElement("p");
        p.className = "hint";
        p.textContent = "В записи нет ожиданий для сравнения.";
        root.appendChild(p);
      } else {
        draft.expectationChecks.forEach((item, idx) => {
          const block = document.createElement("div");
          block.className = "compare-col";
          const q = document.createElement("p");
          q.innerHTML = `<b>${idx + 1}. ${escapeHtml(item.text || "—")}</b>`;
          const options = document.createElement("div");
          options.className = "chips";
          const mk = (label, val) => chip("", label, () => { item.happened = val; renderStep(); }, item.happened === val);
          options.append(mk("Да", "yes"), mk("Нет", "no"), mk("Не совсем", "partial"));
          block.append(q, options);
          root.appendChild(block);
        });
      }
      const nextBtn = document.createElement("button");
      nextBtn.type = "button";
      nextBtn.className = "primary-btn";
      nextBtn.textContent = "Далее";
      nextBtn.addEventListener("click", () => {
        draft.step = 3;
        renderStep();
      });
      actions.append(backBtn, nextBtn);
    } else if (draft.step === 3) {
      const h = document.createElement("h3");
      h.textContent = "3) Что было с ожидаемыми эмоциями?";
      root.appendChild(h);
      if (!draft.emotionChecks.length) {
        const p = document.createElement("p");
        p.className = "hint";
        p.textContent = "В записи нет ожидаемых эмоций для сравнения.";
        root.appendChild(p);
      } else {
        draft.emotionChecks.forEach((item, idx) => {
          const block = document.createElement("div");
          block.className = "compare-col";
          const q = document.createElement("p");
          q.innerHTML = `<b>${idx + 1}. ${escapeHtml(item.emotion || "—")}</b> (ожидалось: ${item.expectedIntensity ?? "—"}%)`;
          const options = document.createElement("div");
          options.className = "chips";
          const mk = (label, val) => chip("", label, () => { item.happened = val; renderStep(); }, item.happened === val);
          options.append(mk("Да", "yes"), mk("Нет", "no"));
          block.append(q, options);
          if (item.happened === "yes") {
            const slider = buildRangePicker(item.actualIntensity ?? 0, (n) => { item.actualIntensity = n; });
            block.appendChild(slider.wrap);
          }
          root.appendChild(block);
        });
      }
      const nextBtn = document.createElement("button");
      nextBtn.type = "button";
      nextBtn.className = "primary-btn";
      nextBtn.textContent = "Далее";
      nextBtn.addEventListener("click", () => {
        draft.step = 4;
        renderStep();
      });
      actions.append(backBtn, nextBtn);
    } else if (draft.step === 4) {
      const columns = document.createElement("div");
      columns.className = "compare-columns";
      const left = document.createElement("div");
      left.className = "compare-col";
      left.innerHTML = `
        <h3>Ожидания</h3>
        <p><b>Ожидания:</b><br>${escapeHtml(expectationsText || "—")}</p>
        <p><b>Ожидаемые эмоции:</b><br>${escapeHtml(emotionsText || "—")}</p>
      `;
      const right = document.createElement("div");
      right.className = "compare-col";
      const expectationsResult = draft.expectationChecks.length
        ? draft.expectationChecks.map((x, i) => {
            const m = x.happened === "yes" ? "да" : x.happened === "partial" ? "не совсем" : x.happened === "no" ? "нет" : "—";
            return `${i + 1}. ${x.text || "—"} → ${m}`;
          }).join("\n")
        : "—";
      const emotionsResult = draft.emotionChecks.length
        ? draft.emotionChecks.map((x, i) => {
            if (x.happened === "yes") return `${i + 1}. ${x.emotion || "—"} → да, ${x.actualIntensity ?? 0}%`;
            if (x.happened === "no") return `${i + 1}. ${x.emotion || "—"} → нет`;
            return `${i + 1}. ${x.emotion || "—"} → —`;
          }).join("\n")
        : "—";
      right.innerHTML = `
        <h3>Реальность</h3>
        <p><b>Как прошло:</b><br>${escapeHtml(draft.whatHappened || "—")}</p>
        <p><b>По ожиданиям:</b><br>${escapeHtml(expectationsResult)}</p>
        <p><b>По эмоциям:</b><br>${escapeHtml(emotionsResult)}</p>
      `;
      columns.append(left, right);
      root.appendChild(columns);

      const summaryField = createInputField(
        "4) Итог сравнения «Ожидания vs Реальность»",
        draft.comparisonSummary,
        "textarea",
        "К чему вы пришли после сравнения двух столбцов?"
      );
      summaryField.input.setAttribute("rows", "4");
      root.appendChild(summaryField.wrap);

      const saveBtn = document.createElement("button");
      saveBtn.type = "button";
      saveBtn.className = "primary-btn";
      saveBtn.textContent = "Сохранить проработку";
      saveBtn.addEventListener("click", () => {
        if (!summaryField.input.value.trim() || !draft.whatHappened.trim()) return;
        draft.comparisonSummary = summaryField.input.value.trim();
        const all = ensureExposureEntryIds();
        const idx = all.findIndex((e) => e.id === entry.id);
        if (idx < 0) return;
        all[idx] = {
          ...all[idx],
          realityReview: {
            whatHappened: draft.whatHappened,
            expectationChecks: draft.expectationChecks,
            emotionChecks: draft.emotionChecks,
            comparisonSummary: draft.comparisonSummary,
            completedAt: new Date().toISOString(),
          },
        };
        setLocalArray("exposure_entries", all);
        updateExposureAlerts();
        state.selectedExposureEntry = all[idx];
        alert("Проработка сохранена. Запись отмечена как завершенная.");
        showPage("exposureHistory");
        renderExposureHistory();
      });
      actions.append(backBtn, saveBtn);
    }

    root.appendChild(actions);
  }

  renderStep();
}

/**
 * Гистограмма эмоций.
 * Важно: после анализа массив emotions_after устроен так —
 * сначала идут переоценки в том же порядке, что и emotions_before (по индексу),
 * затем — только новые эмоции (их не было в «до»). Сопоставление по имени ломалось
 * (дубликаты имён, новые эмоции с ложным «до» = 0).
 */
function buildEmotionChart(beforeList, afterList) {
  const nBefore = beforeList.length;
  if (!nBefore && (!afterList || !afterList.length)) return null;

  const reassessed = afterList.slice(0, nBefore);
  const newAfterOnly = afterList.slice(nBefore);

  const wrap = document.createElement("div");
  wrap.className = "emotion-chart";
  const title = document.createElement("h4");
  title.textContent = "Эмоции до / после (гистограмма)";
  wrap.appendChild(title);

  const pairCount = nBefore;
  const singleCount = newAfterOnly.length;
  const totalCols = pairCount + singleCount;
  if (totalCols === 0) return null;

  const w = 760;
  const h = singleCount ? 240 : 220;
  const left = 38;
  const right = 10;
  const top = 10;
  const bottom = 52;
  const plotW = w - left - right;
  const plotH = h - top - bottom;
  const clusterW = plotW / totalCols;
  const barW = Math.max(5, Math.min(20, clusterW * 0.22));

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);

  [25, 50, 75, 100].forEach((tick) => {
    const y = top + plotH - (tick / 100) * plotH;
    const gl = document.createElementNS("http://www.w3.org/2000/svg", "line");
    gl.setAttribute("x1", String(left));
    gl.setAttribute("x2", String(w - right));
    gl.setAttribute("y1", String(y));
    gl.setAttribute("y2", String(y));
    gl.setAttribute("class", "chart-grid-line");
    svg.appendChild(gl);
  });

  const axisX = document.createElementNS("http://www.w3.org/2000/svg", "line");
  axisX.setAttribute("x1", String(left));
  axisX.setAttribute("x2", String(w - right));
  axisX.setAttribute("y1", String(top + plotH));
  axisX.setAttribute("y2", String(top + plotH));
  axisX.setAttribute("stroke", "rgba(238,243,255,0.55)");
  const axisY = document.createElementNS("http://www.w3.org/2000/svg", "line");
  axisY.setAttribute("x1", String(left));
  axisY.setAttribute("x2", String(left));
  axisY.setAttribute("y1", String(top));
  axisY.setAttribute("y2", String(top + plotH));
  axisY.setAttribute("stroke", "rgba(238,243,255,0.55)");
  svg.append(axisX, axisY);

  [0, 25, 50, 75, 100].forEach((tick) => {
    const y = top + plotH - (tick / 100) * plotH;
    const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
    t.setAttribute("x", "4");
    t.setAttribute("y", String(y + 3));
    t.setAttribute("class", "axis-label");
    t.textContent = String(tick);
    svg.appendChild(t);
  });

  const baseY = top + plotH;

  for (let i = 0; i < pairCount; i++) {
    const cx = left + clusterW * i + clusterW / 2;
    const b = beforeList[i].intensity;
    const a = reassessed[i] ? reassessed[i].intensity : 0;
    const emotion = beforeList[i].emotion || "—";
    const bh = (b / 100) * plotH;
    const ah = (a / 100) * plotH;

    const barB = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    barB.setAttribute("x", String(cx - barW - 2));
    barB.setAttribute("y", String(baseY - bh));
    barB.setAttribute("width", String(barW));
    barB.setAttribute("height", String(bh));
    barB.setAttribute("class", "bar-before");

    const barA = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    barA.setAttribute("x", String(cx + 2));
    barA.setAttribute("y", String(baseY - ah));
    barA.setAttribute("width", String(barW));
    barA.setAttribute("height", String(ah));
    barA.setAttribute("class", "bar-after");

    const lbl = document.createElementNS("http://www.w3.org/2000/svg", "text");
    lbl.setAttribute("x", String(cx));
    lbl.setAttribute("y", String(h - 28));
    lbl.setAttribute("text-anchor", "middle");
    lbl.setAttribute("class", "axis-label");
    const shortEm = emotion.length > 9 ? `${emotion.slice(0, 9)}…` : emotion;
    lbl.textContent = shortEm;

    svg.append(barB, barA, lbl);
  }

  for (let j = 0; j < singleCount; j++) {
    const i = pairCount + j;
    const cx = left + clusterW * i + clusterW / 2;
    const a = newAfterOnly[j].intensity;
    const emotion = newAfterOnly[j].emotion || "—";
    const ah = (a / 100) * plotH;

    const barA = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    barA.setAttribute("x", String(cx - barW / 2));
    barA.setAttribute("y", String(baseY - ah));
    barA.setAttribute("width", String(barW));
    barA.setAttribute("height", String(ah));
    barA.setAttribute("class", "bar-after");

    const lbl = document.createElementNS("http://www.w3.org/2000/svg", "text");
    lbl.setAttribute("x", String(cx));
    lbl.setAttribute("y", String(h - 28));
    lbl.setAttribute("text-anchor", "middle");
    lbl.setAttribute("class", "axis-label");
    const shortEm = emotion.length > 7 ? `${emotion.slice(0, 7)}…` : emotion;
    lbl.textContent = `${shortEm} (новая)`;

    const sub = document.createElementNS("http://www.w3.org/2000/svg", "text");
    sub.setAttribute("x", String(cx));
    sub.setAttribute("y", String(h - 12));
    sub.setAttribute("text-anchor", "middle");
    sub.setAttribute("class", "axis-label");
    sub.textContent = "после";

    svg.append(barA, lbl, sub);
  }

  wrap.appendChild(svg);

  const legendRow = document.createElement("div");
  legendRow.className = "emotion-chart-legend";
  const swBefore = document.createElement("span");
  swBefore.className = "emotion-chart-legend-swatch emotion-chart-legend-swatch--before";
  swBefore.setAttribute("aria-hidden", "true");
  const swAfter = document.createElement("span");
  swAfter.className = "emotion-chart-legend-swatch emotion-chart-legend-swatch--after";
  swAfter.setAttribute("aria-hidden", "true");
  const legBefore = document.createElement("span");
  legBefore.className = "emotion-chart-legend-item";
  legBefore.append(swBefore, document.createTextNode("до анализа"));
  const legAfter = document.createElement("span");
  legAfter.className = "emotion-chart-legend-item";
  legAfter.append(swAfter, document.createTextNode("после анализа"));
  legendRow.append(legBefore, legAfter);
  wrap.appendChild(legendRow);

  return wrap;
}

function buildRangePicker(initialValue, onInput) {
  const wrap = document.createElement("div");
  wrap.className = "intensity-slider-wrap";
  const row = document.createElement("div");
  row.className = "intensity-slider-row";
  const range = document.createElement("input");
  range.type = "range";
  range.min = "0";
  range.max = "100";
  range.step = "1";
  range.value = String(initialValue ?? 0);
  const val = document.createElement("span");
  val.className = "intensity-slider-value";
  val.textContent = range.value;
  range.addEventListener("input", () => {
    const n = Number(range.value);
    val.textContent = String(n);
    onInput(n);
  });
  row.append(range, val);
  wrap.appendChild(row);
  return { wrap, range };
}

function renderThoughtsStep() {
  if (!state.thoughts) return;
  const d = state.thoughts;

  const meta = (() => {
    if (d.step === 1) {
      return {
        badge: "Шаг 1 из 8 · Ситуация",
        title: "Ситуация",
        hint:
          "Описание: где и когда произошло событие? Кто был рядом? Что именно случилось? Важно описывать факты, без интерпретаций.",
      };
    }
    if (d.step === 2) {
      return {
        badge: `Шаг 2 из 8 · Эмоции до анализа${d.emotionsBefore.length ? ` (эмоция ${d.emotionsBefore.length + 1})` : ""}`,
        title: "Какая эмоция была сильнее всего?",
        hint: "Выберите слово из списка или напишите свою ниже. Затем оцените выраженность ползунком от 0 до 100.",
      };
    }
    if (d.step === 3) {
      return {
        badge: "Шаг 2 (продолжение) · Выраженность эмоции",
        title: "Выраженность эмоции",
        hint: "Потяните ползунок от 0 до 100. 0 — почти не чувствовали, 100 — переполняла. Нажмите «Сохранить эмоцию».",
      };
    }
    if (d.step === 4) {
      return {
        badge: "Шаг 2 (продолжение) · Ещё эмоции",
        title: "Была ли ещё эмоция?",
        hint: "Если да — опишите следующую (можно несколько раз). Если перечислили всё важное — нажмите «Нет» и переходим к мыслям.",
      };
    }
    if (d.step === 5) {
      const help = getAutomaticThoughtHelp();
      return {
        badge: "Шаг 3 из 8 · Автоматическая мысль",
        title: "Автоматическая мысль",
        hint:
          "Пример: — «Он зол на меня». Запишите первую автоматическую мысль, которая всплыла в момент ситуации. Обычно это короткая фраза о себе, других или будущем.",
        helpModal: { title: help.title, body: help.body },
      };
    }
    if (d.step === 6) {
      return {
        badge: "Шаг 3 (продолжение) · Уверенность в мысли",
        title: "Насколько вы тогда верили этой мысли?",
        hint: "От 0 (совсем не верю) до 100 (верю полностью). Выберите число и нажмите «Далее».",
      };
    }
    if (d.step === 7) {
      return {
        badge: "Шаг 4 из 8 · Поведение",
        title: "Что вы сделали или хотели сделать?",
        hint: "Реальные действия или импульс: ушли, замолчали, написали сообщение и т.д. Это помогает увидеть связь мысли и поведения.",
      };
    }
    if (d.step === 8) {
      return {
        badge: "Шаг 5 из 8 · Доводы «за»",
        title: `Какие доводы подтверждают мысль: «${d.automaticThought || "..." }»?`,
        hint: "Перечислите все доводы через запятую, не только один. Например: факт 1, факт 2, факт 3.",
      };
    }
    if (d.step === 9) {
      return {
        badge: "Шаг 6 из 8 · Доводы «против»",
        title: `Какие доводы опровергают мысль: «${d.automaticThought || "..."}»?`,
        hint: "Тоже перечислите все доводы через запятую. Добавьте факты, которые не укладываются в автоматическую мысль.",
      };
    }
    if (d.step === 10) {
      const ef = d.evidenceFor || "—";
      const ea = d.evidenceAgainst || "—";
      return {
        badge: "Шаг 7 из 8 · Альтернативная мысль",
        title: "Какая более спокойная или справедливая мысль подходит лучше?",
        hint: `Автоматическая мысль: «${d.automaticThought || "..."}». Доводы за: ${ef}. Доводы против: ${ea}. На основе этого сформулируйте альтернативную мысль.`,
      };
    }
    if (d.step === 11) {
      return {
        badge: "Шаг 7 (продолжение) · Уверенность в новой мысли",
        title: "Насколько вы сейчас верите альтернативной мысли?",
        hint: "Оценка от 0 до 100. Затем можно добавить ещё одну альтернативную формулировку или перейти дальше.",
      };
    }
    if (d.step === 12) {
      return {
        badge: "Шаг 7 (продолжение) · Ещё альтернативы",
        title: "Хотите добавить ещё одну альтернативную мысль?",
        hint: "Иногда полезно сформулировать второй вариант. Если достаточно — нажмите «Нет» и перейдём к переоценке эмоций.",
      };
    }
    if (d.step === 13) {
      const current = d.emotionsBefore[d.reassessIndex];
      const n = d.reassessIndex + 1;
      const total = d.emotionsBefore.length;
      return {
        badge: `Шаг 7 (продолжение) · Переоценка эмоций (${n} из ${total})`,
        title: `Эмоция «${current.emotion}»: как сильно она сейчас?`,
        hint: "Подумайте, как изменилась сила этой эмоции после альтернативных мыслей. Выберите новое значение от 0 до 100 и нажмите «Сохранить».",
      };
    }
    if (d.step === 14) {
      return {
        badge: "Шаг 7 (продолжение) · Новые эмоции",
        title: "Появились ли новые приятные или спокойные эмоции?",
        hint: "Например облегчение, надежда. Выберите из списка, введите своё или нажмите «Нет новых эмоций», если такого не было.",
      };
    }
    if (d.step === 15) {
      return {
        badge: "Шаг 7 (продолжение) · Сила новой эмоции",
        title: "Насколько сильна эта новая эмоция?",
        hint: "Шкала 0–100. Потом можно добавить ещё одну новую эмоцию или завершить блок.",
      };
    }
    if (d.step === 16) {
      return {
        badge: "Шаг 7 (продолжение) · Ещё новые эмоции",
        title: "Появилась ли ещё одна новая эмоция?",
        hint: "Если да — вернёмся к выбору. Если нет — перейдём к финальной заметке.",
      };
    }
    if (d.step === 17) {
      return {
        badge: "Шаг 8 из 8 · Итог",
        title: "Заметка будущему себе",
        hint: "Что вы вынесли из этой записи: что сработало, что заметили впервые. Можно одно предложение. Затем нажмите «Завершить и сохранить».",
      };
    }
    return { badge: "Запись", title: "Новая запись", hint: "" };
  })();

  const card = createWizard("thoughts-entry-root", meta);
  const actions = document.createElement("div");
  actions.className = "wizard-actions";

  if (d.step === 1) {
    const ex = document.createElement("div");
    ex.className = "example-block";
    const exLabel = document.createElement("strong");
    exLabel.textContent = "Пример:";
    const exText = document.createElement("p");
    exText.className = "example-block-text";
    exText.textContent =
      "Понедельник, 10:30. Офис. Начальник Иван Петрович подошел к моему столу, посмотрел на монитор, сказал «Загляни ко мне через час» и ушел, не улыбнувшись.";
    ex.append(exLabel, exText);
    appendToBody(card, ex);
    const f = createInputField("Описание ситуации", d.situation, "textarea", "Опишите факты: где, когда, кто, что произошло…");
    f.input.setAttribute("rows", "5");
    appendToBody(card, f.wrap);
    actions.append(chip("", "Далее", () => {
      if (!f.input.value.trim()) return;
      d.situation = f.input.value.trim();
      d.step = 2;
      renderThoughtsStep();
    }));
  } else if (d.step === 2) {
    const chips = document.createElement("div");
    chips.className = "chips";
    EMOTIONS.forEach((e) => chips.append(chip(e, e, (v) => { d.currentEmotion = v; renderThoughtsStep(); }, d.currentEmotion === e)));
    appendToBody(card, chips);
    const custom = createInputField("Либо напишите свою", d.customEmotion || "", "text", "Например: стыд");
    appendToBody(card, custom.wrap);
    actions.append(chip("", "Продолжить с выбранной эмоцией", () => {
      const c = custom.input.value.trim();
      d.currentEmotion = c || d.currentEmotion;
      if (!d.currentEmotion) return;
      d.step = 3;
      renderThoughtsStep();
    }));
  } else if (d.step === 3) {
    const initial = d.currentIntensity != null ? d.currentIntensity : 0;
    d.currentIntensity = initial;
    const sliderWrap = document.createElement("div");
    sliderWrap.className = "intensity-slider-wrap";
    const row = document.createElement("div");
    row.className = "intensity-slider-row";
    const range = document.createElement("input");
    range.type = "range";
    range.min = "0";
    range.max = "100";
    range.step = "1";
    range.value = String(initial);
    const val = document.createElement("span");
    val.className = "intensity-slider-value";
    val.textContent = range.value;
    range.addEventListener("input", () => {
      const n = Number(range.value);
      d.currentIntensity = n;
      val.textContent = String(n);
    });
    row.append(range, val);
    sliderWrap.appendChild(row);
    appendToBody(card, sliderWrap);
    actions.append(chip("", "Сохранить эмоцию", () => {
      const n = d.currentIntensity != null ? d.currentIntensity : Number(range.value);
      d.emotionsBefore.push({ emotion: d.currentEmotion, intensity: n });
      d.currentEmotion = "";
      d.currentIntensity = null;
      d.step = 4;
      renderThoughtsStep();
    }));
  } else if (d.step === 4) {
    const q = document.createElement("p");
    q.className = "step-question";
    q.textContent = "Нужно ли добавить ещё одну эмоцию, которую вы чувствовали в ситуации?";
    appendToBody(card, q);
    actions.append(
      chip("", "Да, добавить ещё", () => { d.step = 2; renderThoughtsStep(); }),
      chip("", "Нет, перечислил(а) всё", () => { d.step = 5; renderThoughtsStep(); })
    );
  } else if (d.step === 5) {
    const f = createInputField("Автоматическая мысль", d.automaticThought, "textarea", "Например: — «Он зол на меня».");
    f.input.setAttribute("rows", "4");
    appendToBody(card, f.wrap);
    actions.append(chip("", "Далее", () => {
      if (!f.input.value.trim()) return;
      d.automaticThought = f.input.value.trim();
      d.step = 6;
      renderThoughtsStep();
    }));
  } else if (d.step === 6) {
    const initial = d.automaticConfidence != null ? d.automaticConfidence : 0;
    d.automaticConfidence = initial;
    const slider = buildRangePicker(initial, (n) => { d.automaticConfidence = n; });
    appendToBody(card, slider.wrap);
    actions.append(chip("", "Далее", () => { if (d.automaticConfidence === null) return; d.step = 7; renderThoughtsStep(); }));
  } else if (d.step === 7) {
    const f = createInputField("Поведение", d.action, "textarea", "Что сделали или хотели сделать телом, словами, сообщением…");
    f.input.setAttribute("rows", "4");
    appendToBody(card, f.wrap);
    actions.append(chip("", "Далее", () => {
      if (!f.input.value.trim()) return;
      d.action = f.input.value.trim();
      d.step = 8;
      renderThoughtsStep();
    }));
  } else if (d.step === 8) {
    const f = createInputField(`Доводы за мысль «${d.automaticThought || "..."}»`, d.evidenceFor, "textarea", "Пишите через запятую: довод 1, довод 2, довод 3");
    f.input.setAttribute("rows", "4");
    appendToBody(card, f.wrap);
    actions.append(chip("", "Далее", () => {
      if (!f.input.value.trim()) return;
      d.evidenceFor = f.input.value.trim();
      d.step = 9;
      renderThoughtsStep();
    }));
  } else if (d.step === 9) {
    const f = createInputField(`Доводы против мысли «${d.automaticThought || "..."}»`, d.evidenceAgainst, "textarea", "Пишите через запятую: довод 1, довод 2, довод 3");
    f.input.setAttribute("rows", "4");
    appendToBody(card, f.wrap);
    actions.append(chip("", "Далее", () => {
      if (!f.input.value.trim()) return;
      d.evidenceAgainst = f.input.value.trim();
      d.step = 10;
      renderThoughtsStep();
    }));
  } else if (d.step === 10) {
    const contextBlock = document.createElement("div");
    contextBlock.className = "summary";
    contextBlock.textContent = `Контекст:\nАвтоматическая мысль: ${d.automaticThought || "—"}\nДоводы за: ${d.evidenceFor || "—"}\nДоводы против: ${d.evidenceAgainst || "—"}`;
    appendToBody(card, contextBlock);
    const f = createInputField("Альтернативная мысль", d.currentAltThought || "", "textarea", "Более сбалансированная формулировка");
    f.input.setAttribute("rows", "4");
    appendToBody(card, f.wrap);
    actions.append(chip("", "Далее", () => {
      if (!f.input.value.trim()) return;
      d.currentAltThought = f.input.value.trim();
      d.step = 11;
      renderThoughtsStep();
    }));
  } else if (d.step === 11) {
    const initial = d.currentAltConfidence != null ? d.currentAltConfidence : 0;
    d.currentAltConfidence = initial;
    const slider = buildRangePicker(initial, (n) => { d.currentAltConfidence = n; });
    appendToBody(card, slider.wrap);
    actions.append(chip("", "Сохранить эту альтернативу", () => {
      if (d.currentAltConfidence === null) return;
      d.alternativeThoughts.push({ thought: d.currentAltThought, confidence: d.currentAltConfidence });
      d.currentAltThought = "";
      d.currentAltConfidence = null;
      d.step = 12;
      renderThoughtsStep();
    }));
  } else if (d.step === 12) {
    const q = document.createElement("p");
    q.className = "step-question";
    q.textContent = "Хотите записать ещё одну альтернативную формулировку?";
    appendToBody(card, q);
    actions.append(
      chip("", "Да", () => { d.step = 10; renderThoughtsStep(); }),
      chip("", "Нет, достаточно", () => {
        d.reassessIndex = 0;
        d.step = d.emotionsBefore.length ? 13 : 14;
        renderThoughtsStep();
      })
    );
  } else if (d.step === 13) {
    const current = d.emotionsBefore[d.reassessIndex];
    const initial = d.currentReassess != null ? d.currentReassess : 0;
    d.currentReassess = initial;
    const slider = buildRangePicker(initial, (n) => { d.currentReassess = n; });
    appendToBody(card, slider.wrap);
    actions.append(chip("", "Сохранить и дальше", () => {
      if (d.currentReassess === null) return;
      d.emotionsAfter.push({ emotion: current.emotion, intensity: d.currentReassess });
      d.currentReassess = null;
      d.reassessIndex += 1;
      d.step = d.reassessIndex < d.emotionsBefore.length ? 13 : 14;
      renderThoughtsStep();
    }));
  } else if (d.step === 14) {
    const chips = document.createElement("div");
    chips.className = "chips";
    NEW_EMOTIONS.forEach((e) => chips.append(chip(e, e, (v) => { d.currentNewEmotion = v; renderThoughtsStep(); }, d.currentNewEmotion === e)));
    appendToBody(card, chips);
    const custom = createInputField("Своя эмоция", "", "text");
    appendToBody(card, custom.wrap);
    actions.append(
      chip("", "Выбрать и оценить силу", () => {
        const c = custom.input.value.trim();
        d.currentNewEmotion = c || d.currentNewEmotion;
        if (!d.currentNewEmotion) return;
        d.step = 15;
        renderThoughtsStep();
      }),
      chip("", "Нет новых эмоций — к заметке", () => {
        d.step = 17;
        renderThoughtsStep();
      })
    );
  } else if (d.step === 15) {
    const initial = d.currentNewIntensity != null ? d.currentNewIntensity : 0;
    d.currentNewIntensity = initial;
    const slider = buildRangePicker(initial, (n) => { d.currentNewIntensity = n; });
    appendToBody(card, slider.wrap);
    actions.append(chip("", "Сохранить эмоцию", () => {
      if (d.currentNewIntensity === null) return;
      d.emotionsAfter.push({ emotion: d.currentNewEmotion, intensity: d.currentNewIntensity });
      d.currentNewEmotion = "";
      d.currentNewIntensity = null;
      d.step = 16;
      renderThoughtsStep();
    }));
  } else if (d.step === 16) {
    const q = document.createElement("p");
    q.className = "step-question";
    q.textContent = "Добавить ещё одну новую эмоцию?";
    appendToBody(card, q);
    actions.append(
      chip("", "Да", () => { d.step = 14; renderThoughtsStep(); }),
      chip("", "Нет", () => { d.step = 17; renderThoughtsStep(); })
    );
  } else if (d.step === 17) {
    const f = createInputField("Заметка для себя", d.noteToFutureSelf || "", "textarea", "Например: заметил(а), что когда формулирую иначе — тревога падает");
    f.input.setAttribute("rows", "4");
    appendToBody(card, f.wrap);
    actions.append(chip("", "Завершить и сохранить", () => {
      d.noteToFutureSelf = f.input.value.trim();
      d.savedAt = new Date().toISOString();
      d.id = d.id || makeId();
      saveLocal("thought_entries", d);
      renderThoughtHistory();
      const summary = document.createElement("div");
      summary.className = "summary";
      const firstAlt = d.alternativeThoughts[0]?.thought || "—";
      summary.textContent = `Готово. Запись сохранена на этом устройстве.\n\nКороткая сводка:\n• Ситуация: ${d.situation || "—"}\n• Автоматическая мысль: ${d.automaticThought || "—"}\n• Альтернативная мысль: ${firstAlt}`;
      appendToBody(card, summary);
      const chart = buildEmotionChart(d.emotionsBefore, d.emotionsAfter);
      if (chart) appendToBody(card, chart);
      state.thoughts = null;
      actions.innerHTML = "";
    }));
  }

  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "ghost-btn danger-btn";
  cancel.textContent = "Отменить создание записи";
  cancel.addEventListener("click", () => {
    state.thoughts = null;
    document.getElementById("thoughts-entry-root").innerHTML = "";
    showPage("thoughts");
  });
  actions.append(cancel);
  card.append(actions);
}

function renderExposureStep() {
  if (!state.exposure) return;
  const d = state.exposure;

  const meta = (() => {
    if (d.step === 1) {
      return {
        badge: "Шаг 1 из 5 · Событие",
        title: "Как назвать предстоящую ситуацию?",
        hint: "Одна короткая фраза, чтобы потом узнать запись в списке. Например: «Разговор с руководителем» или «Поездка в метро в час пик».",
      };
    }
    if (d.step === 2) {
      return {
        badge: "Шаг 2 из 5 · Дата и время",
        title: "Когда это должно произойти?",
        hint: "Выберите дату и время события на одной строке.",
      };
    }
    if (d.step === 3) {
      return {
        badge: "Шаг 2 из 5 · Ожидания",
        title: "Добавьте ожидание или страх",
        hint: "Записывайте ожидания по одному. Когда всё внесли — нажмите «Ожиданий больше нет».",
      };
    }
    if (d.step === 4) {
      return {
        badge: "Шаг 2 (продолжение) · Вероятность ожидания",
        title: "Насколько вероятно, что это произойдёт?",
        hint: "Оцените в процентах от 0 (совсем не верю) до 100 (точно произойдёт). Нажмите число, затем «Сохранить ожидание».",
      };
    }
    if (d.step === 5) {
      return {
        badge: "Шаг 2 (продолжение) · Ещё ожидания",
        title: "Есть ли ещё ожидание?",
        hint: "Если да — добавьте следующее. Если нет — перейдём к ожидаемым эмоциям.",
      };
    }
    if (d.step === 6) {
      return {
        badge: "Шаг 3 из 5 · Эмоции",
        title: "Какую эмоцию вы ожидаете испытать?",
        hint: "Добавляйте эмоции по одной. Для каждой укажите выраженность от 0 до 100.",
      };
    }
    if (d.step === 7) {
      return {
        badge: "Шаг 3 (продолжение) · Выраженность эмоции",
        title: "Насколько сильной вы ожидаете эту эмоцию?",
        hint: "0 — едва заметно, 100 — очень сильно. Нажмите «Сохранить эмоцию».",
      };
    }
    if (d.step === 8) {
      return {
        badge: "Шаг 3 (продолжение) · Ещё эмоции",
        title: "Есть ли ещё ожидаемая эмоция?",
        hint: "Если да — добавьте следующую. Если нет — перейдём к длительности события.",
      };
    }
    if (d.step === 9) {
      return {
        badge: "Шаг 4 из 5 · Длительность",
        title: "Как долго, по вашему плану, будет длиться событие?",
        hint: "Выберите минуты кнопкой. Это нужно, чтобы напомнить вам подвести итог после окончания. Если хотите разобрать ситуацию позже без напоминания — нажмите «Проработаю сам(а) позже».",
      };
    }
    if (d.step === 10) {
      return {
        badge: "Шаг 5 из 5 · Готово",
        title: "Запись сохранена",
        hint: "План экспозиции записан на этом устройстве. Позже вы сможете добавить, как всё прошло на самом деле.",
      };
    }
    return { badge: "Экспозиция", title: "Новая запись", hint: "" };
  })();

  const card = createWizard("exposure-entry-root", meta);
  const actions = document.createElement("div");
  actions.className = "wizard-actions";

  if (d.step === 1) {
    const f = createInputField("Название ситуации", d.situationName, "textarea", "Кратко, по делу");
    f.input.setAttribute("rows", "3");
    appendToBody(card, f.wrap);
    actions.append(chip("", "Далее", () => {
      if (!f.input.value.trim()) return;
      d.situationName = f.input.value.trim();
      d.step = 2;
      renderExposureStep();
    }));
  } else if (d.step === 2) {
    const inline = document.createElement("div");
    inline.className = "inline-fields";
    const dateField = createInputField("Выберите дату", d.eventDate, "date");
    dateField.input.setAttribute("aria-label", "Дата (ДД.ММ.ГГГГ)");
    const timeField = createInputField("Выберите время", d.eventTime, "time");
    timeField.input.setAttribute("aria-label", "Время (ЧЧ:ММ)");
    inline.append(dateField.wrap, timeField.wrap);
    appendToBody(card, inline);
    actions.append(chip("", "Далее", () => {
      if (!dateField.input.value || !timeField.input.value) return;
      d.eventDate = dateField.input.value;
      d.eventTime = timeField.input.value;
      d.step = 3;
      renderExposureStep();
    }));
  } else if (d.step === 3) {
    const f = createInputField("Ваше ожидание или страх", d.currentExpectation || "", "textarea");
    f.input.setAttribute("rows", "4");
    appendToBody(card, f.wrap);
    actions.append(chip("", "Далее", () => {
      if (!f.input.value.trim()) return;
      d.currentExpectation = f.input.value.trim();
      d.step = 4;
      renderExposureStep();
    }));
  } else if (d.step === 4) {
    const initial = d.currentProbability != null ? d.currentProbability : 0;
    d.currentProbability = initial;
    const slider = buildRangePicker(initial, (n) => { d.currentProbability = n; });
    appendToBody(card, slider.wrap);
    actions.append(chip("", "Сохранить ожидание", () => {
      if (d.currentProbability === null) return;
      d.expectationsData.push({ text: d.currentExpectation, probability: d.currentProbability });
      d.currentExpectation = "";
      d.currentProbability = null;
      d.step = 5;
      renderExposureStep();
    }));
  } else if (d.step === 5) {
    const q = document.createElement("p");
    q.className = "step-question";
    q.textContent = "Добавить ещё одно ожидание или страх?";
    appendToBody(card, q);
    actions.append(
      chip("", "Да, добавить", () => { d.step = 3; renderExposureStep(); }),
      chip("", "Ожиданий больше нет", () => { d.step = 6; renderExposureStep(); })
    );
  } else if (d.step === 6) {
    const chips = document.createElement("div");
    chips.className = "chips";
    EMOTIONS.forEach((e) => chips.append(chip(e, e, (v) => { d.currentEmotion = v; renderExposureStep(); }, d.currentEmotion === e)));
    appendToBody(card, chips);
    const custom = createInputField("Своя эмоция", "", "text");
    appendToBody(card, custom.wrap);
    actions.append(chip("", "Продолжить с выбранной эмоцией", () => {
      const c = custom.input.value.trim();
      d.currentEmotion = c || d.currentEmotion;
      if (!d.currentEmotion) return;
      d.step = 7;
      renderExposureStep();
    }));
  } else if (d.step === 7) {
    const initial = d.currentIntensity != null ? d.currentIntensity : 0;
    d.currentIntensity = initial;
    const slider = buildRangePicker(initial, (n) => { d.currentIntensity = n; });
    appendToBody(card, slider.wrap);
    actions.append(chip("", "Сохранить эмоцию", () => {
      if (d.currentIntensity === null) return;
      d.emotionsBefore.push({ emotion: d.currentEmotion, intensity: d.currentIntensity });
      d.currentEmotion = "";
      d.currentIntensity = null;
      d.step = 8;
      renderExposureStep();
    }));
  } else if (d.step === 8) {
    const q = document.createElement("p");
    q.className = "step-question";
    q.textContent = "Нужно ли добавить ещё одну ожидаемую эмоцию?";
    appendToBody(card, q);
    actions.append(
      chip("", "Да", () => { d.step = 6; renderExposureStep(); }),
      chip("", "Нет, достаточно", () => { d.step = 9; renderExposureStep(); })
    );
  } else if (d.step === 9) {
    const chips = document.createElement("div");
    chips.className = "chips";
    DURATIONS.forEach((m) => chips.append(chip(m, String(m), (v) => { d.durationMinutes = v; renderExposureStep(); }, d.durationMinutes === m)));
    appendToBody(card, chips);
    const note = document.createElement("p");
    note.className = "hint";
    note.style.marginTop = "10px";
    note.textContent = "После выбора минут нажмите «Сохранить план».";
    appendToBody(card, note);
    actions.append(
      chip("", "Проработаю сам(а) позже", () => {
        d.durationMinutes = null;
        d.manualProcessing = true;
        d.step = 10;
        renderExposureStep();
      }),
      chip("", "Сохранить план", () => {
        if (!d.durationMinutes) return;
        d.manualProcessing = false;
        d.step = 10;
        renderExposureStep();
      })
    );
  } else if (d.step === 10) {
    d.eventDatetime = `${d.eventDate} ${d.eventTime}:00`;
    d.savedAt = new Date().toISOString();
    d.id = d.id || makeId();
    saveLocal("exposure_entries", d);
    updateExposureAlerts();
    renderExposureHistory();
    const summary = document.createElement("div");
    summary.className = "summary";
    summary.textContent = `Сохранено на этом устройстве.\n\n• Ситуация: ${d.situationName}\n• Начало: ${formatEventDateTime(d.eventDate, d.eventTime)}\n• Записано ожиданий: ${d.expectationsData.length}\n• Ожидаемых эмоций: ${d.emotionsBefore.length}\n• Режим: ${d.manualProcessing ? "без таймера — вернётесь к записи сами" : `напоминание после ${d.durationMinutes} мин от начала`}`;
    appendToBody(card, summary);
    actions.innerHTML = "";
    state.exposure = null;
    actions.append(chip("", "К меню экспозиции", () => showPage("exposure")));
  }

  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "ghost-btn danger-btn";
  cancel.textContent = "Отменить создание записи";
  cancel.addEventListener("click", () => {
    state.exposure = null;
    const root = document.getElementById("exposure-entry-root");
    if (root) root.innerHTML = "";
    showPage("exposure");
  });
  if (d.step !== 10) {
    actions.append(cancel);
  }
  card.append(actions);
}

homeBtn?.addEventListener("click", () => showPage("dashboard"));

document.getElementById("open-thought-entry-btn")?.addEventListener("click", () => {
  showPage("thoughtsCreate");
  state.thoughts = {
    step: 1,
    situation: "",
    emotionsBefore: [],
    currentEmotion: "",
    currentIntensity: null,
    automaticThought: "",
    automaticConfidence: null,
    action: "",
    evidenceFor: "",
    evidenceAgainst: "",
    currentAltThought: "",
    currentAltConfidence: null,
    alternativeThoughts: [],
    emotionsAfter: [],
    reassessIndex: 0,
    currentReassess: null,
    currentNewEmotion: "",
    currentNewIntensity: null,
    noteToFutureSelf: "",
  };
  renderThoughtsStep();
});

const thoughtHistoryBtn = document.getElementById("open-thought-history-btn");
const thoughtExportBtn = document.getElementById("open-thought-export-btn");
const thoughtBulkDeleteBtn = document.getElementById("open-thought-bulk-delete-btn");
const thoughtHistorySearch = document.getElementById("thoughts-history-search");
if (thoughtHistoryBtn) {
  thoughtHistoryBtn.addEventListener("click", () => {
    showPage("thoughtsHistory");
    renderThoughtHistory();
  });
}
if (thoughtHistorySearch) {
  thoughtHistorySearch.addEventListener("input", () => renderThoughtHistory());
}
if (thoughtExportBtn) {
  thoughtExportBtn.addEventListener("click", () => {
    showPage("thoughtsExport");
    updateRangeCustomVisibility("thought-export-range", "thought-export-custom");
  });
}
if (thoughtBulkDeleteBtn) {
  thoughtBulkDeleteBtn.addEventListener("click", () => {
    showPage("thoughtsBulkDelete");
    updateRangeCustomVisibility("thought-delete-range", "thought-delete-custom");
  });
}
["filter-situation", "filter-automatic-thought", "filter-emotions"].forEach((id) => {
  const el = document.getElementById(id);
  if (el) el.addEventListener("change", () => renderThoughtHistory());
});

const backToThoughtsBtn = document.getElementById("back-to-thoughts-btn");
if (backToThoughtsBtn) {
  backToThoughtsBtn.addEventListener("click", () => showPage("thoughts"));
}

const backToHistoryBtn = document.getElementById("back-to-history-btn");
if (backToHistoryBtn) {
  backToHistoryBtn.addEventListener("click", () => {
    showPage("thoughtsHistory");
    renderThoughtHistory();
  });
}

const backToThoughtsFromExportBtn = document.getElementById("back-to-thoughts-from-export-btn");
if (backToThoughtsFromExportBtn) {
  backToThoughtsFromExportBtn.addEventListener("click", () => showPage("thoughts"));
}

const backToThoughtsFromDeleteBtn = document.getElementById("back-to-thoughts-from-delete-btn");
if (backToThoughtsFromDeleteBtn) {
  backToThoughtsFromDeleteBtn.addEventListener("click", () => showPage("thoughts"));
}

document.querySelectorAll('input[name="thought-export-range"]').forEach((el) => {
  el.addEventListener("change", () => updateRangeCustomVisibility("thought-export-range", "thought-export-custom"));
});
document.querySelectorAll('input[name="thought-delete-range"]').forEach((el) => {
  el.addEventListener("change", () => updateRangeCustomVisibility("thought-delete-range", "thought-delete-custom"));
});

const downloadThoughtsPeriodBtn = document.getElementById("download-thoughts-period-btn");
if (downloadThoughtsPeriodBtn) {
  downloadThoughtsPeriodBtn.addEventListener("click", () => {
    const range = getSelectedRange("thought-export-range");
    const from = document.getElementById("thought-export-from")?.value || "";
    const to = document.getElementById("thought-export-to")?.value || "";
    const entries = getThoughtEntriesByRange(range, from, to);
    if (!entries.length) {
      alert("Нет записей за выбранный период.");
      return;
    }
    downloadThoughtEntriesExcel(entries, `thought_entries_${range}_${new Date().toISOString().slice(0, 10)}`);
  });
}

const deleteThoughtsPeriodBtn = document.getElementById("delete-thoughts-period-btn");
if (deleteThoughtsPeriodBtn) {
  deleteThoughtsPeriodBtn.addEventListener("click", async () => {
    const range = getSelectedRange("thought-delete-range");
    const from = document.getElementById("thought-delete-from")?.value || "";
    const to = document.getElementById("thought-delete-to")?.value || "";
    const entries = getThoughtEntriesByRange(range, from, to);
    if (!entries.length) {
      alert("Нет записей за выбранный период.");
      return;
    }
    const ok = await askDeleteConfirm(`Вы уверены, что хотите удалить записи (${entries.length} шт.)?`);
    if (!ok) return;
    const toDeleteIds = new Set(entries.map((e) => e.id));
    const all = ensureThoughtEntryIds();
    const next = all.filter((e) => !toDeleteIds.has(e.id));
    setLocalArray("thought_entries", next);
    if (state.selectedThoughtEntry && toDeleteIds.has(state.selectedThoughtEntry.id)) {
      state.selectedThoughtEntry = null;
    }
    alert(`Удалено записей: ${entries.length}`);
    showPage("thoughts");
  });
}

const deleteThoughtRecordBtn = document.getElementById("delete-thought-record-btn");
if (deleteThoughtRecordBtn) {
  deleteThoughtRecordBtn.addEventListener("click", async () => {
    const entry = state.selectedThoughtEntry;
    if (!entry) return;
    if (!(await askDeleteConfirm())) return;
    deleteThoughtEntryById(entry.id);
    state.selectedThoughtEntry = null;
    showPage("thoughtsHistory");
    renderThoughtHistory();
  });
}

const downloadThoughtRecordBtn = document.getElementById("download-thought-record-btn");
if (downloadThoughtRecordBtn) {
  downloadThoughtRecordBtn.addEventListener("click", () => {
    const entry = state.selectedThoughtEntry;
    if (!entry) return;
    downloadThoughtEntryExcel(entry);
  });
}

document.getElementById("open-exposure-entry-btn")?.addEventListener("click", () => {
  showPage("exposureCreate");
  state.exposure = {
    step: 1,
    situationName: "",
    eventDate: "",
    eventTime: "",
    currentExpectation: "",
    currentProbability: null,
    expectationsData: [],
    currentEmotion: "",
    currentIntensity: null,
    emotionsBefore: [],
    durationMinutes: null,
    manualProcessing: false,
  };
  renderExposureStep();
});

document.getElementById("open-exposure-history-btn")?.addEventListener("click", () => {
  updateExposureAlerts();
  showPage("exposureHistory");
  renderExposureHistory();
});
document.getElementById("exposure-history-search")?.addEventListener("input", () => renderExposureHistory());
document.querySelectorAll('input[name="exposure-status-filter"]').forEach((el) => {
  el.addEventListener("change", () => renderExposureHistory());
});

document.getElementById("open-exposure-export-btn")?.addEventListener("click", () => {
  showPage("exposureExport");
  updateRangeCustomVisibility("exposure-export-range", "exposure-export-custom");
});

document.getElementById("open-exposure-bulk-delete-btn")?.addEventListener("click", () => {
  showPage("exposureBulkDelete");
  updateRangeCustomVisibility("exposure-delete-range", "exposure-delete-custom");
});

document.getElementById("back-to-exposure-btn")?.addEventListener("click", () => showPage("exposure"));
document.getElementById("back-to-exposure-from-export-btn")?.addEventListener("click", () => showPage("exposure"));
document.getElementById("back-to-exposure-from-delete-btn")?.addEventListener("click", () => showPage("exposure"));
document.getElementById("back-to-exposure-history-btn")?.addEventListener("click", () => {
  showPage("exposureHistory");
  renderExposureHistory();
});

document.querySelectorAll('input[name="exposure-export-range"]').forEach((el) => {
  el.addEventListener("change", () => updateRangeCustomVisibility("exposure-export-range", "exposure-export-custom"));
});
document.querySelectorAll('input[name="exposure-delete-range"]').forEach((el) => {
  el.addEventListener("change", () => updateRangeCustomVisibility("exposure-delete-range", "exposure-delete-custom"));
});

document.getElementById("download-exposure-period-btn")?.addEventListener("click", () => {
  const range = getSelectedRange("exposure-export-range");
  const from = document.getElementById("exposure-export-from")?.value || "";
  const to = document.getElementById("exposure-export-to")?.value || "";
  const entries = getExposureEntriesByRange(range, from, to);
  if (!entries.length) {
    alert("Нет записей за выбранный период.");
    return;
  }
  downloadExposureEntriesExcel(entries, `exposure_entries_${range}_${new Date().toISOString().slice(0, 10)}`);
});

document.getElementById("delete-exposure-period-btn")?.addEventListener("click", async () => {
  const range = getSelectedRange("exposure-delete-range");
  const from = document.getElementById("exposure-delete-from")?.value || "";
  const to = document.getElementById("exposure-delete-to")?.value || "";
  const entries = getExposureEntriesByRange(range, from, to);
  if (!entries.length) {
    alert("Нет записей за выбранный период.");
    return;
  }
  const ok = await askDeleteConfirm(`Вы уверены, что хотите удалить записи (${entries.length} шт.)?`);
  if (!ok) return;
  const toDeleteIds = new Set(entries.map((e) => e.id));
  const all = ensureExposureEntryIds();
  const next = all.filter((e) => !toDeleteIds.has(e.id));
  setLocalArray("exposure_entries", next);
  updateExposureAlerts();
  alert(`Удалено записей: ${entries.length}`);
  showPage("exposure");
});

document.getElementById("open-act-case-btn")?.addEventListener("click", () => {
  openActCase().catch(() => {});
});
document.getElementById("open-act-case-extra-btn")?.addEventListener("click", () => {
  openActCase(true).catch(() => {});
});
document.getElementById("back-to-act-btn")?.addEventListener("click", () => showPage("act"));
document.getElementById("back-from-achievements-btn")?.addEventListener("click", () => showPage("dashboard"));

updateExposureAlerts();
renderDashboard();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./sw.js").catch(() => {});
  });
}
