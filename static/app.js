const syncBtn = document.getElementById("syncBtn");
const configBtn = document.getElementById("configBtn");
const repoLabel = document.getElementById("repoLabel");
const titlePrefixLabel = document.getElementById("titlePrefixLabel");
const dbLabel = document.getElementById("dbLabel");
const viewMode = document.getElementById("viewMode");
const stateFilter = document.getElementById("stateFilter");
const issueIds = document.getElementById("issueIds");
const showNoteDefault = document.getElementById("showNoteDefault");
const sortBy = document.getElementById("sortBy");
const sortDir = document.getElementById("sortDir");
const groupBy = document.getElementById("groupBy");
const createdFrom = document.getElementById("createdFrom");
const createdFromPicker = document.getElementById("createdFromPicker");
const createdFromSelectBtn = document.getElementById("createdFromSelectBtn");
const createdFromClearBtn = document.getElementById("createdFromClearBtn");
const createdTo = document.getElementById("createdTo");
const createdToPicker = document.getElementById("createdToPicker");
const createdToSelectBtn = document.getElementById("createdToSelectBtn");
const createdToClearBtn = document.getElementById("createdToClearBtn");
const updatedFrom = document.getElementById("updatedFrom");
const updatedFromPicker = document.getElementById("updatedFromPicker");
const updatedFromSelectBtn = document.getElementById("updatedFromSelectBtn");
const updatedFromClearBtn = document.getElementById("updatedFromClearBtn");
const updatedTo = document.getElementById("updatedTo");
const updatedToPicker = document.getElementById("updatedToPicker");
const updatedToSelectBtn = document.getElementById("updatedToSelectBtn");
const updatedToClearBtn = document.getElementById("updatedToClearBtn");
const configModal = document.getElementById("configModal");
const repoInput = document.getElementById("repoInput");
const titlePrefixInput = document.getElementById("titlePrefixInput");
const configCancelBtn = document.getElementById("configCancelBtn");
const configSaveBtn = document.getElementById("configSaveBtn");
const statusEl = document.getElementById("status");
const summaryEl = document.getElementById("summary");
const listEl = document.getElementById("list");

const state = {
  repo: "dotnet/runtime",
  titlePrefix: "[ci-scan]",
  view: "all",
  issueState: "all",
  issueIds: "",
  sortBy: "createdAt",
  sortDir: "desc",
  groupBy: "none",
  showNoteByDefault: false,
  createdFrom: "",
  createdTo: "",
  updatedFrom: "",
  updatedTo: "",
  loading: false
};

function escapeHtml(v) {
  return String(v)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatDate(value) {
  if (!value) return "-";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "-" : d.toLocaleString();
}

function formatGroupDate(value) {
  if (!value) return "Unknown";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "Unknown";
  return d.toLocaleDateString();
}

function renderIssueCard(x) {
  const noteIsShown = state.showNoteByDefault || !x.analyzedDone;
  const noteSectionClass = noteIsShown ? "note-section" : "note-section collapsed";
  const noteToggleText = noteIsShown ? "Hide note" : "Show note";
  return `
    <div class="item" data-id="${x.id}">
      <div class="top">
        <h2 class="title"><a href="${x.url}" target="_blank" rel="noreferrer">#${x.number} ${escapeHtml(x.title)}</a></h2>
        <span class="badge ${x.analyzedDone ? "done" : "pending"}">${x.analyzedDone ? "Analyzed" : "Pending"}</span>
      </div>
      <div class="meta">State: ${x.state} · Created: ${formatDate(x.createdAt)} · Updated: ${formatDate(x.updatedAt)}</div>
      <button type="button" class="note-toggle" aria-expanded="${String(noteIsShown)}">${noteToggleText}</button>
      <div class="${noteSectionClass}">
        <textarea placeholder="Analysis result note...">${escapeHtml(x.note || "")}</textarea>
      </div>
      <div class="actions">
        <label><input type="checkbox" ${x.analyzedDone ? "checked" : ""}> Mark analysis done</label>
        <button class="quick-complete">Mark analyzed: completed</button>
        <button class="save">Save</button>
      </div>
    </div>
  `;
}

function renderGroupedIssues(rows) {
  if (state.groupBy === "none") {
    return rows.map((x) => renderIssueCard(x)).join("");
  }

  const groups = new Map();
  for (const row of rows) {
    const key = state.groupBy === "status" ? `Status: ${row.state || "unknown"}` : `Created date: ${formatGroupDate(row.createdAt)}`;
    if (!groups.has(key)) {
      groups.set(key, []);
    }
    groups.get(key).push(row);
  }

  const entries = Array.from(groups.entries());
  if (state.groupBy === "status") {
    const statusOrder = { "Status: open": 0, "Status: closed": 1 };
    entries.sort((a, b) => {
      const rankA = statusOrder[a[0]] ?? 2;
      const rankB = statusOrder[b[0]] ?? 2;
      if (rankA !== rankB) return rankA - rankB;
      return a[0].localeCompare(b[0]);
    });
  }

  return entries
    .map(([label, issues]) => `
      <section class="issue-group">
        <h3 class="issue-group-title">${escapeHtml(label)} <span class="muted">(${issues.length})</span></h3>
        <div class="issue-group-list">
          ${issues.map((x) => renderIssueCard(x)).join("")}
        </div>
      </section>
    `)
    .join("");
}

async function getJson(url, options = undefined) {
  const resp = await fetch(url, options);
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.error || `Request failed: ${resp.status}`);
  }
  return data;
}

function applyProjectConfig(config) {
  const safe = config && typeof config === "object" ? config : {};

  state.repo = typeof safe.repo === "string" && safe.repo ? safe.repo : state.repo;
  state.titlePrefix = typeof safe.titlePrefix === "string" && safe.titlePrefix ? safe.titlePrefix : state.titlePrefix;

  repoLabel.textContent = state.repo;
  titlePrefixLabel.textContent = state.titlePrefix;
  dbLabel.textContent = `data/${state.repo.replace("/", "_")}_issues.db`;
  repoInput.value = state.repo;
  titlePrefixInput.value = state.titlePrefix;
}

async function loadProjectConfig() {
  const res = await getJson("/api/project-config");
  applyProjectConfig(res.config || {});
}

function openConfigModal() {
  repoInput.value = state.repo;
  titlePrefixInput.value = state.titlePrefix;
  configModal.classList.remove("hidden");
}

function closeConfigModal() {
  configModal.classList.add("hidden");
}

async function saveProjectConfig() {
  const repo = repoInput.value.trim();
  const titlePrefix = titlePrefixInput.value.trim();
  const repoParts = repo.split("/");
  if (repoParts.length !== 2 || repoParts.some((part) => !part.trim())) {
    statusEl.textContent = "Repository must use owner/repo format.";
    return;
  }
  if (!titlePrefix) {
    statusEl.textContent = "Title prefix is required.";
    return;
  }

  const res = await getJson("/api/project-config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo, titlePrefix })
  });
  applyProjectConfig(res.config || {});
  closeConfigModal();
  statusEl.textContent = "Config saved. Sync from GitHub to load issues for this repo and title prefix.";
  await refreshSummary();
  await loadIssues();
}

function getConfigPayload() {
  return {
    view: state.view,
    state: state.issueState,
    issueIds: state.issueIds,
    sortBy: state.sortBy,
    sortDir: state.sortDir,
    groupBy: state.groupBy,
    showNoteByDefault: state.showNoteByDefault,
    createdFrom: state.createdFrom,
    createdTo: state.createdTo,
    updatedFrom: state.updatedFrom,
    updatedTo: state.updatedTo
  };
}

function toPickerDateTime(value) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const pad2 = (n) => String(n).padStart(2, "0");
  const year = d.getFullYear();
  const month = pad2(d.getMonth() + 1);
  const day = pad2(d.getDate());
  const hour = pad2(d.getHours());
  const minute = pad2(d.getMinutes());
  return `${year}-${month}-${day}T${hour}:${minute}`;
}

function applyDashboardConfig(config) {
  const safe = config && typeof config === "object" ? config : {};

  state.view = typeof safe.view === "string" ? safe.view : state.view;
  state.issueState = typeof safe.state === "string" ? safe.state : state.issueState;
  state.issueIds = typeof safe.issueIds === "string" ? safe.issueIds : "";
  state.sortBy = typeof safe.sortBy === "string" ? safe.sortBy : state.sortBy;
  state.sortDir = typeof safe.sortDir === "string" ? safe.sortDir : state.sortDir;
  state.groupBy = typeof safe.groupBy === "string" ? safe.groupBy : state.groupBy;
  state.showNoteByDefault = Boolean(safe.showNoteByDefault);
  state.createdFrom = typeof safe.createdFrom === "string" ? safe.createdFrom : "";
  state.createdTo = typeof safe.createdTo === "string" ? safe.createdTo : "";
  state.updatedFrom = typeof safe.updatedFrom === "string" ? safe.updatedFrom : "";
  state.updatedTo = typeof safe.updatedTo === "string" ? safe.updatedTo : "";

  viewMode.value = state.view;
  stateFilter.value = state.issueState;
  issueIds.value = state.issueIds;
  sortBy.value = state.sortBy;
  sortDir.value = state.sortDir;
  groupBy.value = state.groupBy;
  showNoteDefault.checked = state.showNoteByDefault;

  createdFrom.value = state.createdFrom;
  createdTo.value = state.createdTo;
  updatedFrom.value = state.updatedFrom;
  updatedTo.value = state.updatedTo;

  createdFromPicker.value = toPickerDateTime(state.createdFrom);
  createdToPicker.value = toPickerDateTime(state.createdTo);
  updatedFromPicker.value = toPickerDateTime(state.updatedFrom);
  updatedToPicker.value = toPickerDateTime(state.updatedTo);
}

async function loadDashboardConfig() {
  const res = await getJson("/api/config");
  applyDashboardConfig(res.config || {});
}

async function saveDashboardConfig() {
  await getJson("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(getConfigPayload())
  });
}

async function loadIssuesAndPersistConfig() {
  await loadIssues();
  await saveDashboardConfig();
}

async function refreshSummary() {
  const summary = await getJson("/api/summary");
  summaryEl.textContent = `${summary.analyzed}/${summary.total} analyzed`;
}

function wireActions() {
  for (const card of listEl.querySelectorAll(".item")) {
    const id = Number(card.getAttribute("data-id"));
    const noteSectionEl = card.querySelector(".note-section");
    const noteToggleBtn = card.querySelector("button.note-toggle");
    const noteEl = card.querySelector("textarea");
    const doneEl = card.querySelector("input[type='checkbox']");
    const saveBtn = card.querySelector("button.save");
    const quickCompleteBtn = card.querySelector("button.quick-complete");

    noteToggleBtn.addEventListener("click", () => {
      const isCollapsed = noteSectionEl.classList.toggle("collapsed");
      noteToggleBtn.textContent = isCollapsed ? "Show note" : "Hide note";
      noteToggleBtn.setAttribute("aria-expanded", String(!isCollapsed));
    });

    saveBtn.addEventListener("click", async () => {
      try {
        await getJson(`/api/issues/${id}/analysis`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            analyzedDone: doneEl.checked,
            note: noteEl.value.trim()
          })
        });
        await refreshSummary();
        statusEl.textContent = "Saved analysis.";
        await loadIssues();
      } catch (err) {
        statusEl.textContent = `Save failed: ${err.message}`;
      }
    });

    quickCompleteBtn.addEventListener("click", async () => {
      try {
        await getJson(`/api/issues/${id}/analysis`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            analyzedDone: true,
            note: "completed"
          })
        });
        await refreshSummary();
        statusEl.textContent = "Marked analysis completed.";
        await loadIssues();
      } catch (err) {
        statusEl.textContent = `Quick complete failed: ${err.message}`;
      }
    });
  }
}

async function loadIssues() {
  const qs = new URLSearchParams({
    view: state.view,
    state: state.issueState,
    sortBy: state.sortBy,
    sortDir: state.sortDir
  });
  if (state.issueIds) qs.set("issueIds", state.issueIds);
  if (state.createdFrom) qs.set("createdFrom", state.createdFrom);
  if (state.createdTo) qs.set("createdTo", state.createdTo);
  if (state.updatedFrom) qs.set("updatedFrom", state.updatedFrom);
  if (state.updatedTo) qs.set("updatedTo", state.updatedTo);

  const rows = await getJson(`/api/issues?${qs.toString()}`);

  if (!rows.length) {
    listEl.innerHTML = `<div class="muted">No issues to display.</div>`;
    return;
  }

  listEl.innerHTML = renderGroupedIssues(rows);

  wireActions();
}

async function syncIssues() {
  if (state.loading) return;
  state.loading = true;
  syncBtn.disabled = true;
  statusEl.textContent = "Syncing from GitHub...";

  try {
    const res = await getJson("/api/sync", { method: "POST" });
    statusEl.textContent = `Sync complete. ${res.count} issues in local datasource.`;
    await refreshSummary();
    await loadIssues();
  } catch (err) {
    statusEl.textContent = `Sync failed: ${err.message}`;
  } finally {
    state.loading = false;
    syncBtn.disabled = false;
  }
}

syncBtn.addEventListener("click", syncIssues);
configBtn.addEventListener("click", openConfigModal);
configCancelBtn.addEventListener("click", closeConfigModal);
configSaveBtn.addEventListener("click", async () => {
  try {
    await saveProjectConfig();
  } catch (err) {
    statusEl.textContent = `Config save failed: ${err.message}`;
  }
});
configModal.addEventListener("click", (event) => {
  if (event.target === configModal) {
    closeConfigModal();
  }
});
viewMode.addEventListener("change", async () => {
  state.view = viewMode.value;
  await loadIssuesAndPersistConfig();
});
stateFilter.addEventListener("change", async () => {
  state.issueState = stateFilter.value;
  await loadIssuesAndPersistConfig();
});
issueIds.addEventListener("change", async () => {
  state.issueIds = issueIds.value.trim();
  try {
    await loadIssuesAndPersistConfig();
  } catch (err) {
    statusEl.textContent = `Issue ID filter failed: ${err.message}`;
  }
});
showNoteDefault.addEventListener("change", async () => {
  state.showNoteByDefault = showNoteDefault.checked;
  await loadIssuesAndPersistConfig();
});
sortBy.addEventListener("change", async () => {
  state.sortBy = sortBy.value;
  await loadIssuesAndPersistConfig();
});
sortDir.addEventListener("change", async () => {
  state.sortDir = sortDir.value;
  await loadIssuesAndPersistConfig();
});
groupBy.addEventListener("change", async () => {
  state.groupBy = groupBy.value;
  await loadIssuesAndPersistConfig();
});

function toIsoOrEmpty(v) {
  if (!v) return "";
  const normalized = String(v).trim().replace(" ", "T");
  const d = new Date(normalized);
  return Number.isNaN(d.getTime()) ? "" : d.toISOString();
}

function openPicker(picker) {
  if (typeof picker.showPicker === "function") {
    picker.showPicker();
    return;
  }
  picker.click();
}

async function applyDateTextInput(inputEl, key) {
  const raw = inputEl.value.trim();
  if (!raw) {
    state[key] = "";
    await loadIssuesAndPersistConfig();
    return;
  }

  const iso = toIsoOrEmpty(raw);
  if (!iso) {
    statusEl.textContent = "Invalid datetime format. Use YYYY-MM-DDTHH:mm.";
    return;
  }

  state[key] = iso;
  await loadIssuesAndPersistConfig();
}

function bindDateInput(textInput, pickerInput, selectBtn, key) {
  textInput.addEventListener("change", async () => {
    await applyDateTextInput(textInput, key);
  });

  selectBtn.addEventListener("click", () => {
    openPicker(pickerInput);
  });

  pickerInput.addEventListener("change", async () => {
    textInput.value = pickerInput.value;
    await applyDateTextInput(textInput, key);
  });
}

bindDateInput(createdFrom, createdFromPicker, createdFromSelectBtn, "createdFrom");
bindDateInput(createdTo, createdToPicker, createdToSelectBtn, "createdTo");
bindDateInput(updatedFrom, updatedFromPicker, updatedFromSelectBtn, "updatedFrom");
bindDateInput(updatedTo, updatedToPicker, updatedToSelectBtn, "updatedTo");

async function clearSingleDateFilter(textInput, pickerInput, key) {
  textInput.value = "";
  pickerInput.value = "";
  state[key] = "";
  await loadIssuesAndPersistConfig();
}

createdFromClearBtn.addEventListener("click", async () => {
  await clearSingleDateFilter(createdFrom, createdFromPicker, "createdFrom");
});
createdToClearBtn.addEventListener("click", async () => {
  await clearSingleDateFilter(createdTo, createdToPicker, "createdTo");
});
updatedFromClearBtn.addEventListener("click", async () => {
  await clearSingleDateFilter(updatedFrom, updatedFromPicker, "updatedFrom");
});
updatedToClearBtn.addEventListener("click", async () => {
  await clearSingleDateFilter(updatedTo, updatedToPicker, "updatedTo");
});

async function init() {
  try {
    try {
      await loadProjectConfig();
    } catch {
      statusEl.textContent = "Could not load project config. Using defaults.";
    }
    try {
      await loadDashboardConfig();
    } catch {
      statusEl.textContent = "Could not load saved filters. Using defaults.";
    }
    await refreshSummary();
    await loadIssues();
  } catch (err) {
    statusEl.textContent = `Initialization failed: ${err.message}`;
  }
}

init();
