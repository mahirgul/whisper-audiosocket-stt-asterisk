/* ============================================================
   audiosocket.js — AudioSocket Monitor page logic
   ============================================================ */

"use strict";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let activeConnections = {};  // uuid → { uuid, stage, chunks, ... }
let sseSource = null;
let historyPage = 1;
let openSessionUuid = null;

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  loadStatus();
  loadHistory(1);
  connectSSE();
  // Poll status every 5 s
  setInterval(loadStatus, 5000);
});

// ---------------------------------------------------------------------------
// Server-Sent Events
// ---------------------------------------------------------------------------
function connectSSE() {
  if (sseSource) sseSource.close();

  sseSource = new EventSource("/audiosocket/stream");

  sseSource.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      handleSSEEvent(msg.event, msg.data);
    } catch (_) {}
  };

  sseSource.onerror = () => {
    // Reconnect after 3 s
    sseSource.close();
    setTimeout(connectSSE, 3000);
  };
}

function handleSSEEvent(eventType, data) {
  appendLog(eventType, data);

  switch (eventType) {
    case "connection_open":
      activeConnections[data.uuid] = {
        uuid: data.uuid,
        remote: data.remote_addr,
        stage: "Connected — recording audio",
        chunks: 0,
        startedAt: data.timestamp
      };
      renderActiveConnections();
      loadStatus();
      break;

    case "chunk_received":
      if (activeConnections[data.uuid]) {
        activeConnections[data.uuid].chunks = data.chunk_idx;
        activeConnections[data.uuid].stage = `Processing chunk #${data.chunk_idx}`;
        renderActiveConnections();
      }
      break;

    case "transcribed":
      if (activeConnections[data.uuid]) {
        activeConnections[data.uuid].stage = `Transcribed`;
        renderActiveConnections();
      }
      break;

    case "delivered":
      if (activeConnections[data.uuid]) {
        activeConnections[data.uuid].stage =
          `Delivered chunk #${data.chunk_idx} (HTTP ${data.status_code})`;
        renderActiveConnections();
      }
      break;

    case "connection_close":
      if (data.status === "processing") {
        // Call ended, processing started in background
        if (activeConnections[data.uuid]) {
          activeConnections[data.uuid].stage = "📞 Call ended — processing audio…";
          renderActiveConnections();
        }
      } else {
        delete activeConnections[data.uuid];
        renderActiveConnections();
      }
      loadStatus();
      break;

    case "session_queued":
      if (activeConnections[data.uuid]) {
        activeConnections[data.uuid].stage = `⌛ Queued for processing (Position: ${data.queue_position})`;
        renderActiveConnections();
      }
      break;

    case "processing_started":
      if (activeConnections[data.uuid]) {
        activeConnections[data.uuid].stage = "🔄 Transcribing audio…";
        renderActiveConnections();
      }
      break;

    case "session_processed":
      delete activeConnections[data.uuid];
      renderActiveConnections();
      loadStatus();
      loadHistory(historyPage);
      break;

    case "debug_info":
      // Just for logging in the live console
      break;

    case "error":
      if (activeConnections[data.uuid]) {
        activeConnections[data.uuid].stage = `⚠ Error: ${data.message}`;
        renderActiveConnections();
      }
      break;
  }
}

// ---------------------------------------------------------------------------
// Live log
// ---------------------------------------------------------------------------
const LOG_CLASS = {
  connection_open:  "ev-open",
  session_queued:   "ev-open",
  chunk_received:   "ev-chunk",
  transcribed:      "ev-tran",
  translated:       "ev-tran",
  dubbed:           "ev-dub",
  delivered:        "ev-dub",
  connection_close: "ev-close",
  error:            "ev-error",
};

function appendLog(eventType, data) {
  const log = document.getElementById("liveLog");
  if (!log) return;

  const now = new Date().toLocaleTimeString();
  const cls = LOG_CLASS[eventType] || "";
  const uuid = (data.uuid || "").substring(0, 8);
  const detail = eventType === "transcribed" || eventType === "translated"
    ? ` — "${(data.text || "").substring(0, 60)}${data.text && data.text.length > 60 ? "…" : ""}"`
    : eventType === "chunk_received"
      ? ` — ${data.duration_ms}ms`
      : eventType === "connection_close"
        ? ` — ${data.total_chunks} chunks, ${data.duration_s}s`
        : eventType === "session_queued"
          ? ` — Position: ${data.queue_position}`
          : eventType === "debug_info"
            ? ` — ${data.message}`
            : "";

  const entry = document.createElement("div");
  entry.className = "log-entry";
  entry.innerHTML =
    `<span class="log-time">[${now}]</span> ` +
    `<span class="log-event ${cls}">${eventType.toUpperCase()}</span> ` +
    `<span style="color:#475569">${uuid}…</span>${detail}`;

  log.appendChild(entry);
  // Keep last 200 lines
  while (log.children.length > 200) log.removeChild(log.firstChild);
  log.scrollTop = log.scrollHeight;
}

// ---------------------------------------------------------------------------
// Active connections
// ---------------------------------------------------------------------------
function renderActiveConnections() {
  const el = document.getElementById("activeConnections");
  if (!el) return;

  const list = Object.values(activeConnections);
  if (list.length === 0) {
    el.innerHTML = `
      <div class="monitor-empty">
        <div class="icon">📡</div>
        <div>No active connections</div>
      </div>`;
    return;
  }

  el.innerHTML = list.map(conn => `
    <div class="conn-card">
      <div class="conn-uuid">${conn.uuid}</div>
      <div class="conn-stage">${conn.stage}</div>
      <div class="conn-chunks">Chunks processed: <strong>${conn.chunks}</strong></div>
      ${conn.remote ? `<div class="conn-chunks" style="margin-top:3px;">Remote: ${conn.remote}</div>` : ""}
    </div>
  `).join("");
}

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------
async function loadStatus() {
  try {
    const r = await fetch("/audiosocket/status");
    const s = await r.json();

    const badge = document.getElementById("serverStatus");
    if (badge) {
      badge.className = `status-badge ${s.listening ? "listening" : "stopped"}`;
      badge.innerHTML = `
        <span class="dot"></span>
        ${s.listening ? `Listening :${s.port}` : "Stopped"}
      `;
    }

    const portLbl = document.getElementById("serverPortLabel");
    if (portLbl) portLbl.textContent = s.port;

    const cnt = document.getElementById("activeCount");
    if (cnt) cnt.textContent = s.active_connections;

  } catch (_) {
    const badge = document.getElementById("serverStatus");
    if (badge) {
      badge.className = "status-badge stopped";
      badge.innerHTML = `<span class="dot"></span> Unreachable`;
    }
  }
}

// ---------------------------------------------------------------------------
// Session history
// ---------------------------------------------------------------------------
async function loadHistory(page) {
  historyPage = page;
  try {
    const r = await fetch(`/audiosocket/sessions?page=${page}&limit=15`);
    const data = await r.json();
    renderHistory(data);
  } catch (e) {
    document.getElementById("sessionList").innerHTML =
      `<div style="color:#f87171;font-size:0.75rem;">Failed to load history</div>`;
  }
}

function renderHistory(data) {
  const list = document.getElementById("sessionList");
  const pag  = document.getElementById("histPagination");

  // Stats pills
  const totalEl = document.getElementById("totalSessions");
  if (totalEl) totalEl.textContent = data.total;

  // Reset bulk actions UI
  const bulk = document.getElementById("bulkActions");
  if (bulk) bulk.style.display = "none";
  const selectAll = document.getElementById("selectAll");
  if (selectAll) selectAll.checked = false;
  updateSelectedCount();

  if (!data.items || data.items.length === 0) {
    list.innerHTML = `
      <div class="monitor-empty">
        <div class="icon">📂</div>
        <div>No sessions yet</div>
      </div>`;
    pag.innerHTML = "";
    return;
  }

  list.innerHTML = data.items.map(s => {
    const short = s.uuid.substring(0, 18) + "…";
    const statusTag = `<span class="tag ${s.status || 'unknown'}">${s.status || 'unknown'}</span>`;
    const chunks = `<span class="tag">${s.total_chunks ?? 0} chunks</span>`;
    const lang   = `<span class="tag">${s.target_lang || 'original'}</span>`;
    const dur    = `<span class="tag">${Math.round(s.duration_s || 0)}s</span>`;

    let timeStr = "";
    if (s.started) {
      const d = new Date(s.started);
      if (!isNaN(d.getTime())) {
        timeStr = d.toLocaleString();
      } else {
        // If it's a number (float seconds)
        const d2 = new Date(parseFloat(s.started) * 1000);
        if (!isNaN(d2.getTime())) timeStr = d2.toLocaleString();
      }
    }

    return `
      <div class="session-item" id="sess_${s.uuid}" onclick="toggleSession('${s.uuid}')">
        <div class="session-header">
          <div style="display:flex; align-items:center; gap:10px;">
            <input type="checkbox" class="item-checkbox" value="${s.uuid}" onclick="toggleSelect(event)">
            <div style="display:flex; flex-direction:column; gap:2px;">
              <span class="session-uuid" title="${s.uuid}">${short}</span>
              <span class="session-time">${timeStr}</span>
            </div>
          </div>
          <div class="session-meta">${lang}${chunks}${dur}${statusTag}</div>
        </div>
        <div class="session-detail" id="detail_${s.uuid}">
          <div style="font-size:0.65rem;color:#94a3b8;margin-bottom:10px;">
            Loading chunks…
          </div>
        </div>
      </div>`;
  }).join("");

  // Pagination
  pag.innerHTML = "";
  for (let p = 1; p <= data.pages; p++) {
    const btn = document.createElement("button");
    btn.className = `page-btn${p === data.page ? " active" : ""}`;
    btn.textContent = p;
    btn.onclick = () => loadHistory(p);
    pag.appendChild(btn);
  }
}

async function toggleSession(uuid) {
  const item   = document.getElementById(`sess_${uuid}`);
  const detail = document.getElementById(`detail_${uuid}`);
  if (!item || !detail) return;

  const isOpen = item.classList.contains("active");

  // Close all
  document.querySelectorAll(".session-item.active").forEach(el => {
    el.classList.remove("active");
  });

  if (isOpen) { openSessionUuid = null; return; }

  item.classList.add("active");
  openSessionUuid = uuid;
  await loadSessionDetail(uuid, detail);
}

async function loadSessionDetail(uuid, container) {
  container.innerHTML = `<div style="font-size:0.65rem;color:#94a3b8;">Loading…</div>`;
  try {
    const r = await fetch(`/audiosocket/sessions/${uuid}`);
    if (!r.ok) throw new Error("Not found");
    const data = await r.json();

    if (!data.chunks || data.chunks.length === 0) {
      container.innerHTML = `<div style="font-size:0.7rem;color:#94a3b8;">No chunks recorded yet.</div>`;
      return;
    }

    const chunksHtml = data.chunks.map(chunk => {
      const origText = chunk.orig_srt_content
        ? extractTextFromSrt(chunk.orig_srt_content) : "–";

      const links = [
        chunk.wav      ? `<a class="chunk-link" href="${chunk.wav}" target="_blank">WAV</a>` : "",
        chunk.orig_srt ? `<a class="chunk-link" href="${chunk.orig_srt}" target="_blank">ORIG SRT</a>` : "",
      ].filter(Boolean).join("");

      return `
        <div class="chunk-item">
          <div class="chunk-idx">CHUNK #${String(chunk.index).padStart(3, "0")}</div>
          <div class="chunk-text">
            <strong>Text:</strong> ${escHtml(origText)}
          </div>
          <div class="chunk-actions">${links}</div>
        </div>`;
    }).join("");

    const zipBtn = `
      <a href="/audiosocket/sessions/${uuid}/download-zip" class="chunk-link" style="margin-top:12px; display:inline-block; border-color:#3b82f6; color:#3b82f6;">
        ZIP (Full Session)
      </a>`;

    const deleteBtn = `
      <span class="chunk-link" style="margin-top:12px; margin-left:6px; display:inline-block; color:#ef4444; border-color:#fee2e2;"
        onclick="deleteSession('${uuid}')">
        DELETE
      </span>`;

    container.innerHTML = `<div class="chunk-list">${chunksHtml}</div><div style="margin-top:4px;">${zipBtn}${deleteBtn}</div>`;

  } catch (e) {
    container.innerHTML = `<div style="color:#f87171;font-size:0.7rem;">Error: ${e.message}</div>`;
  }
}

function playInline(url, id) {
  const audio = document.getElementById(`audio_${id}`);
  if (!audio) return;
  if (audio.style.display === "none") {
    audio.src = url;
    audio.style.display = "block";
    audio.play();
  } else {
    audio.style.display = "none";
    audio.pause();
    audio.src = "";
  }
}

async function deleteSession(uuid) {
  if (!confirm(`Delete session ${uuid.substring(0, 8)}…?`)) return;
  try {
    const r = await fetch(`/audiosocket/sessions/${uuid}`, { method: "DELETE" });
    if (r.ok) {
      showToast("Session deleted", "success");
      loadHistory(historyPage);
    } else {
      const err = await r.json();
      showToast("Delete failed: " + (err.detail || "Unknown error"), "error");
    }
  } catch (e) {
    showToast("Error: " + e.message, "error");
  }
}

function toggleSelect(event) {
  event.stopPropagation();
  updateSelectedCount();
}

function toggleSelectAll() {
  const master = document.getElementById("selectAll");
  const checks = document.querySelectorAll(".item-checkbox");
  checks.forEach(c => c.checked = master.checked);
  updateSelectedCount();
}

function updateSelectedCount() {
  const checks = document.querySelectorAll(".item-checkbox:checked");
  const count = checks.length;
  const bulk = document.getElementById("bulkActions");
  const countEl = document.getElementById("selectedCount");

  if (bulk) bulk.style.display = count > 0 ? "flex" : "none";
  if (countEl) countEl.textContent = `${count} selected`;
}

async function deleteSelectedSessions() {
  const checks = document.querySelectorAll(".item-checkbox:checked");
  const uuids = Array.from(checks).map(c => c.value);
  if (uuids.length === 0) return;

  if (!confirm(`Delete ${uuids.length} selected sessions?`)) return;

  try {
    const r = await fetch("/audiosocket/bulk-delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(uuids)
    });
    if (r.ok) {
      showToast(`${uuids.length} sessions deleted`, "success");
      loadHistory(historyPage);
    } else {
      const err = await r.json();
      showToast("Delete failed: " + (err.detail || "Unknown error"), "error");
    }
  } catch (e) {
    showToast("Error: " + e.message, "error");
  }
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
function extractTextFromSrt(srt) {
  return srt
    .split("\n")
    .filter(l => l && !/^\d+$/.test(l.trim()) && !l.includes("-->"))
    .join(" ")
    .replace(/\[.*?\]/g, "")
    .trim()
    .substring(0, 120);
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function getVal(id)              { return (document.getElementById(id) || {}).value; }
function setVal(id, v)           { const el = document.getElementById(id); if (el) el.value = v ?? ""; }
function getChecked(id)          { return !!(document.getElementById(id) || {}).checked; }
function setChecked(id, v)       { const el = document.getElementById(id); if (el) el.checked = !!v; }

function showToast(msg, type = "success") {
  let t = document.getElementById("toast");
  if (!t) {
    t = document.createElement("div");
    t.id = "toast";
    t.className = "toast";
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.className = `toast ${type}`;
  // Force reflow
  void t.offsetWidth;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 3000);
}
