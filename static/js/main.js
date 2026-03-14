// ── Node colors ───────────────────────────────────────────────────────────────

const NODE_COLORS = {
  // Logical operators
  TableScan:           "#22c55e",
  Filter:              "#f97316",
  Projection:          "#3b82f6",
  Aggregate:           "#a855f7",
  Sort:                "#06b6d4",
  Limit:               "#f43f5e",
  Join:                "#eab308",
  // Physical operators (looked up after stripping trailing "Exec")
  DataSource:          "#22c55e",
  SortPreservingMerge: "#06b6d4",
  GlobalLimit:         "#f43f5e",
  LocalLimit:          "#f43f5e",
  HashJoin:            "#eab308",
  Repartition:         "#ec4899",
  CoalesceBatches:     "#6366f1",
};

function nodeColor(type) {
  return NODE_COLORS[type] ?? NODE_COLORS[type.replace(/Exec$/, "")] ?? "#64748b";
}

// ── Shared Cytoscape style ────────────────────────────────────────────────────

const CY_STYLE = [
  {
    selector: "node",
    style: {
      "label":           "data(label)",
      "background-color": (ele) => nodeColor(ele.data("type")),
      "color":           "#fff",
      "font-family":     "ui-monospace, monospace",
      "font-size":       "14px",
      "text-valign":     "center",
      "text-halign":     "center",
      "text-wrap":       "wrap",
      "text-max-width":  "200px",
      "width":           "label",
      "height":          "label",
      "padding":         "12px",
      "shape":           "roundrectangle",
      "border-width":    1.5,
      "border-color":    "#ffffff22",
    },
  },
  {
    selector: "edge",
    style: {
      "width":               1.5,
      "line-color":          "#334155",
      "target-arrow-color":  "#334155",
      "target-arrow-shape":  "triangle",
      "curve-style":         "bezier",
    },
  },
  {
    selector: "node:selected",
    style: { "border-color": "#4f6ef7", "border-width": 2.5 },
  },
  // Diff status border styles
  {
    selector: "node[diff='added']",
    style: { "border-color": "#22c55e", "border-width": 2.5 },
  },
  {
    selector: "node[diff='removed']",
    style: { "border-color": "#f43f5e", "border-width": 2.5, "opacity": 0.5 },
  },
  {
    selector: "node[diff='modified']",
    style: { "border-color": "#eab308", "border-width": 2.5 },
  },
];

const LAYOUT = { name: "breadthfirst", directed: true, spacingFactor: 1.4, padding: 40 };

// ── Cytoscape instances ───────────────────────────────────────────────────────

let cy = null;

if (typeof cytoscape !== "undefined") {
  cy = cytoscape({ container: document.getElementById("cy"), style: CY_STYLE, elements: [] });
} else {
  console.error("Cytoscape.js not loaded. Graph visualization is disabled.");
}

let cyLeft  = null;
let cyRight = null;

function initDiffInstances() {
  if (cyLeft || typeof cytoscape === "undefined") return;
  cyLeft  = cytoscape({ container: document.getElementById("cy-left"),  style: CY_STYLE, elements: [] });
  cyRight = cytoscape({ container: document.getElementById("cy-right"), style: CY_STYLE, elements: [] });
  wireInstance(cyLeft);
  wireInstance(cyRight);
}

// ── Tooltip ───────────────────────────────────────────────────────────────────

const tooltip = document.getElementById("tooltip");

function wireTooltip(instance) {
  if (!instance) return;
  instance.on("mouseover", "node", (e) => {
    const pos   = e.renderedPosition;
    const cRect = instance.container().getBoundingClientRect();
    const wRect = document.querySelector(".graph-wrapper").getBoundingClientRect();
    tooltip.textContent    = e.target.data("label");
    tooltip.style.display  = "block";
    tooltip.style.left     = (pos.x + cRect.left - wRect.left + 12) + "px";
    tooltip.style.top      = (pos.y + cRect.top  - wRect.top  + 12) + "px";
  });
  instance.on("mouseout", "node", () => { tooltip.style.display = "none"; });
}

// ── Detail panel ──────────────────────────────────────────────────────────────

function showDetail(data) {
  const typeEl   = document.getElementById("detail-type");
  const labelEl  = document.getElementById("detail-label");
  const schemaEl = document.getElementById("detail-schema");

  typeEl.textContent   = data.type;
  typeEl.style.background = nodeColor(data.type);
  labelEl.textContent  = data.label;

  schemaEl.innerHTML = "";
  const cols = data.schema ?? [];

  if (cols.length === 0) {
    schemaEl.innerHTML = '<span class="detail-empty">No schema information</span>';
  } else {
    for (const col of cols) {
      const chip = document.createElement("div");
      chip.className = "schema-chip";
      chip.innerHTML =
        `<span class="chip-name">${col.name}</span>` +
        `<span class="chip-type">${col.type}</span>` +
        (col.nullable ? `<span class="chip-null">N</span>` : "");
      schemaEl.appendChild(chip);
    }
  }

  document.getElementById("detail-panel").classList.add("visible");
}

function closeDetail() {
  document.getElementById("detail-panel").classList.remove("visible");
  if (cy) cy.elements().unselect();
  if (cyLeft)  cyLeft.elements().unselect();
  if (cyRight) cyRight.elements().unselect();
}

function wireInstance(instance) {
  if (!instance) return;
  wireTooltip(instance);
  instance.on("tap", "node", (e) => showDetail(e.target.data()));
  instance.on("tap", (e) => { if (e.target === instance) closeDetail(); });
}

if (cy) wireInstance(cy);

// ── Plan rendering ────────────────────────────────────────────────────────────

function renderSingle(elements) {
  document.getElementById("cy").classList.remove("hidden");
  document.getElementById("cy-diff-wrapper").classList.remove("visible");
  document.getElementById("diff-legend").style.display = "none";
  if (!cy) return;
  cy.elements().remove();
  cy.add(elements);
  cy.layout(LAYOUT).run();
  cy.fit(undefined, 40);
}

function renderDiff(left, right) {
  document.getElementById("cy").classList.add("hidden");
  document.getElementById("cy-diff-wrapper").classList.add("visible");
  document.getElementById("diff-legend").style.display = "flex";

  // Lazy-initialize after the containers are visible so Cytoscape gets
  // correct dimensions on first render.
  initDiffInstances();

  if (!cyLeft || !cyRight) return;

  cyLeft.elements().remove();
  cyLeft.add(left);
  cyLeft.layout({ ...LAYOUT, padding: 20 }).run();
  cyLeft.fit(undefined, 20);

  cyRight.elements().remove();
  cyRight.add(right);
  cyRight.layout({ ...LAYOUT, padding: 20 }).run();
  cyRight.fit(undefined, 20);
}

// ── Mode selector ─────────────────────────────────────────────────────────────

let currentMode = "logical";

document.querySelectorAll(".mode-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelector(".mode-btn.active").classList.remove("active");
    btn.classList.add("active");
    currentMode = btn.dataset.mode;
  });
});

// ── SQL editor (Textarea) ─────────────────────────────────────────────────────

const sqlInput = document.getElementById("sql-input");
const _INITIAL_SQL =
  "SELECT * FROM test";

sqlInput.value = _INITIAL_SQL;

function getSql() {
  return sqlInput.value.trim();
}

function updateEditorSchema(tables) {
  // No-op for textarea version
}

// Support Cmd+Enter or Ctrl+Enter to run
sqlInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
    e.preventDefault();
    runQuery();
  }
});

// ── Plan query ────────────────────────────────────────────────────────────────

async function runQuery() {
  const sqlText = getSql();
  const btn     = document.getElementById("run-btn");
  const errDiv  = document.getElementById("error");

  if (!sqlText) return;

  btn.disabled    = true;
  btn.textContent = "Running…";
  errDiv.style.display = "none";

  try {
    const resp = await fetch("/plan", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ sql: sqlText, plan_type: currentMode }),
    });

    const data = await resp.json();

    if (!resp.ok) {
      errDiv.textContent   = data.detail ?? "Unknown error";
      errDiv.style.display = "block";
      return;
    }

    addToHistory(sqlText, currentMode);
    closeDetail();
    if (data.type === "single") {
      renderSingle(data.elements);
    } else {
      renderDiff(data.left, data.right);
    }
  } catch (err) {
    errDiv.textContent   = String(err);
    errDiv.style.display = "block";
  } finally {
    btn.disabled    = false;
    btn.textContent = "Run";
  }
}

// ── Table sidebar ─────────────────────────────────────────────────────────────

function renderTables(tables) {
  console.log("renderTables called with:", tables);
  updateEditorSchema(tables);

  const container = document.getElementById("tables-list");
  console.log("Tables container:", container);
  container.innerHTML = "";

  if (tables.length === 0) {
    container.innerHTML = '<div style="padding:12px 16px;font-size:11px;color:#475569;">No tables registered</div>';
    return;
  }

  for (const table of tables) {
    const item = document.createElement("div");
    item.className = "table-item";

    const nameRow = document.createElement("div");
    nameRow.className = "table-name";
    nameRow.innerHTML =
      `<span class="table-chevron">▶</span>` +
      `<span>${table.name}</span>` +
      `<button class="table-remove" title="Remove table" data-name="${table.name}">✕</button>`;

    const colsEl = document.createElement("div");
    colsEl.className = "table-columns";

    for (const col of table.columns) {
      const row = document.createElement("div");
      row.className = "column-row";
      row.innerHTML = `<span class="col-name">${col.name}</span><span class="col-type">${col.type}</span>`;
      colsEl.appendChild(row);
    }

    nameRow.addEventListener("click", (e) => {
      if (e.target.closest(".table-remove")) return;
      const isOpen = colsEl.style.display === "block";
      colsEl.style.display = isOpen ? "none" : "block";
      nameRow.querySelector(".table-chevron").classList.toggle("open", !isOpen);
    });

    nameRow.querySelector(".table-remove").addEventListener("click", (e) => {
      e.stopPropagation();
      removeTable(table.name);
    });

    item.appendChild(nameRow);
    item.appendChild(colsEl);
    container.appendChild(item);
  }
}

async function loadTables() {
  const resp = await fetch("/tables");
  const data = await resp.json();
  console.log("Initial tables load:", data);
  renderTables(data.tables);
}

async function removeTable(name) {
  const resp = await fetch(`/tables/${encodeURIComponent(name)}`, { method: "DELETE" });
  const data = await resp.json();
  if (!resp.ok) {
    alert(data.detail ?? "Failed to remove table");
    return;
  }
  renderTables(data.tables);
}

// ── File upload / drag-and-drop ───────────────────────────────────────────────

const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");

// Prevent browser from opening dropped files by default
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());

dropZone.addEventListener("click", (e) => {
  if (dropZone.classList.contains("loading")) {
    e.preventDefault();
  }
});

let dragCounter = 0;

dropZone.addEventListener("dragenter", (e) => {
  e.preventDefault();
  dragCounter++;
  dropZone.classList.add("drag-over");
});

dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
});

dropZone.addEventListener("dragleave", (e) => {
  e.preventDefault();
  dragCounter--;
  if (dragCounter === 0) {
    dropZone.classList.remove("drag-over");
  }
});

dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dragCounter = 0;
  dropZone.classList.remove("drag-over");
  const file = e.dataTransfer.files[0];
  if (file) uploadFile(file);
});

fileInput.addEventListener("change", () => {
  if (fileInput.files[0]) uploadFile(fileInput.files[0]);
});

const SUPPORTED_EXTENSIONS = new Set([".csv", ".json", ".avro"]);

async function uploadFile(file) {
  const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (!SUPPORTED_EXTENSIONS.has(ext)) {
    alert("Unsupported file type. Please upload a .csv, .json, or .avro file.");
    return;
  }

  console.log(`Uploading file: ${file.name} (${file.size} bytes)`);
  dropZone.classList.add("loading");
  dropZone.innerHTML = `Registering <strong>${file.name}</strong>…`;

  const formData = new FormData();
  formData.append("file", file);

  try {
    const resp = await fetch("/tables", { method: "POST", body: formData });
    const data = await resp.json();

    console.log("Server response:", resp.status, data);

    if (!resp.ok) {
      alert(data.detail ?? "Failed to register table");
      return;
    }

    console.log("Rendering updated tables:", data.tables);
    renderTables(data.tables);
  } catch (err) {
    console.error("Upload error:", err);
    alert(String(err));
  } finally {
    dropZone.classList.remove("loading");
    dropZone.innerHTML = 'Drop CSV, JSON, or Avro to register table<br><span style="color:#334155">or click to browse</span>';
    fileInput.value = "";
  }
}

// ── Query history ─────────────────────────────────────────────────────────────

const HISTORY_KEY = "datafusion_query_history";
const HISTORY_MAX = 20;

function loadHistory() {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) ?? "[]");
  } catch {
    return [];
  }
}

function saveHistory(entries) {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(entries));
}

function addToHistory(sqlText, plan_type) {
  const entries = loadHistory().filter((e) => e.sql !== sqlText);
  entries.unshift({ sql: sqlText, plan_type, timestamp: Date.now() });
  saveHistory(entries.slice(0, HISTORY_MAX));
  renderHistory();
}

function formatTimeAgo(ts) {
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60)   return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function renderHistory() {
  const list    = document.getElementById("history-list");
  const entries = loadHistory();

  if (entries.length === 0) {
    list.innerHTML = '<div class="history-empty">No queries yet</div>';
    return;
  }

  list.innerHTML = "";
  for (const entry of entries) {
    const item = document.createElement("div");
    item.className = "history-item";
    item.innerHTML =
      `<span class="history-sql">${entry.sql.replace(/</g, "&lt;")}</span>` +
      `<span class="history-meta">` +
        `<span class="history-mode">${entry.plan_type}</span>` +
        `<span class="history-time">${formatTimeAgo(entry.timestamp)}</span>` +
      `</span>`;
    item.addEventListener("click", () => {
      // Load the SQL into the textarea
      sqlInput.value = entry.sql;
      document.querySelector(".mode-btn.active").classList.remove("active");
      const target = document.querySelector(`.mode-btn[data-mode="${entry.plan_type}"]`);
      if (target) { target.classList.add("active"); currentMode = entry.plan_type; }
      closeHistory();
      runQuery();
    });
    list.appendChild(item);
  }
}

function toggleHistory() {
  const dd = document.getElementById("history-dropdown");
  if (dd.classList.contains("open")) {
    closeHistory();
  } else {
    renderHistory();
    dd.classList.add("open");
  }
}

function closeHistory() {
  document.getElementById("history-dropdown").classList.remove("open");
}

function clearHistory() {
  saveHistory([]);
  renderHistory();
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.getElementById("run-btn").addEventListener("click", runQuery);
document.getElementById("detail-close-btn").addEventListener("click", closeDetail);
document.getElementById("history-btn").addEventListener("click", toggleHistory);
document.getElementById("history-clear-btn").addEventListener("click", clearHistory);

document.addEventListener("click", (e) => {
  const wrapper = document.querySelector(".history-wrapper");
  if (wrapper && !wrapper.contains(e.target)) closeHistory();
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeHistory();
});

loadTables();
runQuery();
