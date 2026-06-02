async function fetchJSON(url, options = {}) {
  const res = await fetch(url, options);
  return await res.json();
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

let allProtocols = [];

async function loadProtocols() {
  const out = await fetchJSON("/api/protocols");
  allProtocols = out.protocols || [];

  const select = document.getElementById("protocol-select");
  if (!select) return;

  const current = select.value;
  select.innerHTML = "";

  for (const p of allProtocols) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.name;
    select.appendChild(opt);
  }

  const customOpt = document.createElement("option");
  customOpt.value = "custom";
  customOpt.textContent = "Custom protocol";
  select.appendChild(customOpt);

  if (current) {
    select.value = current;
  } else if (allProtocols.length) {
    select.value = allProtocols[0].id;
  }

  toggleCustomProtocol();
  updateProtocolSummary();
}

function getSelectedProtocol() {
  const select = document.getElementById("protocol-select");
  const id = select.value;
  if (id === "custom") {
    return getCustomProtocolData();
  }
  return allProtocols.find(p => p.id === id) || null;
}

function getCustomProtocolData() {
  const name = document.getElementById("custom-name").value || "My protocol";
  const temp = Number(document.getElementById("custom-temp").value || 65);
  const duration = Number(document.getElementById("custom-time").value || 45);
  const warmup = Number(document.getElementById("custom-warmup").value || 1);
  const interval = Number(document.getElementById("custom-interval").value || 30);

  return {
    id: "custom",
    name: name,
    temperature_c: temp,
    duration_min: duration,
    warmup_min: warmup,
    read_interval_s: interval
  };
}

function updateProtocolSummary() {
  const p = getSelectedProtocol();
  if (!p) return;

  setText("summary-temp", `${p.temperature_c} °C`);
  setText("summary-duration", `${p.duration_min} min`);
  setText("summary-warmup", `${p.warmup_min} min`);
  setText("summary-interval", `${p.read_interval_s} s`);

  const saveName = document.getElementById("save-protocol-name");
  if (saveName && document.getElementById("protocol-select").value === "custom") {
    saveName.value = p.name;
  }
}

function toggleCustomProtocol() {
  const mode = document.getElementById("protocol-select").value;
  const panel = document.getElementById("custom-protocol-panel");
  if (!panel) return;
  panel.style.display = mode === "custom" ? "block" : "none";
  updateProtocolSummary();
}

async function saveCustomProtocol() {
  const feedback = document.getElementById("save-feedback");
  const data = getCustomProtocolData();
  const saveName = document.getElementById("save-protocol-name").value.trim() || data.name;
  data.name = saveName;

  feedback.textContent = "Saving...";

  const out = await fetchJSON("/api/protocols/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data)
  });

  feedback.textContent = out.message || out.error || "Done";
  await loadProtocols();
}

async function startRun() {
  const mode = document.getElementById("protocol-select").value;
  let payload = {};

  if (mode === "custom") {
    payload = {
      protocol_id: "custom",
      custom_protocol: getCustomProtocolData()
    };
  } else {
    payload = { protocol_id: mode };
  }

  const out = await fetchJSON("/api/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  setText("banner", out.message || out.error || "Started");
}

async function stopRun() {
  const out = await fetchJSON("/api/stop", {
    method: "POST",
    headers: { "Content-Type": "application/json" }
  });
  setText("banner", out.message || out.error || "Stopped");
}

async function resetRun() {
  const out = await fetchJSON("/api/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" }
  });
  setText("banner", out.message || out.error || "Reset");
}

function updateStateUI(state) {
  setText("frame-count", String(state.frames_captured || 0));
  setText("last-file", state.last_file || "-");

  const temp = state.current_temp_c == null ? "--" : `${state.current_temp_c.toFixed(1)} °C`;
  setText("metric-temp", temp);
  setText("metric-time", `${(state.current_time_min || 0).toFixed(1)} min`);
  setText("metric-status", state.assay_status || "idle");

  const confirmed = (state.chambers || []).filter(c => c.confirmed).length;
  const total = (state.chambers || []).length;
  setText("metric-detected", `${confirmed} / ${total}`);
  updateFinalResults(state);

  const logBox = document.getElementById("log-box");
  if (logBox) {
    logBox.textContent = (state.log || []).join("\n");
    logBox.scrollTop = logBox.scrollHeight;
  }

  const tbody = document.getElementById("chamber-table");
  if (tbody) {
    tbody.innerHTML = "";
    for (const ch of (state.chambers || [])) {
      const latest = ch.corrected_display && ch.corrected_display.length
        ? Math.round(ch.corrected_display[ch.corrected_display.length - 1])
        : 0;

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${ch.chamber_id}</td>
        <td>${ch.status_text}</td>
        <td>${ch.tt_display_min == null ? "—" : ch.tt_display_min.toFixed(1) + " min"}</td>
        <td>${latest}</td>
      `;
      tbody.appendChild(tr);
    }
  }

  if (typeof updateChart === "function") {
    updateChart(state);
  }

  if (typeof updateTopStatus === "function") {
    updateTopStatus(state);
  }
}

function formatResultCall(call) {
  if (call === "positive") return "Positive";
  if (call === "negative") return "Negative";
  if (call === "rejected") return "Rejected";
  return "Pending";
}

function updateFinalResults(state) {
  const grid = document.getElementById("final-result-grid");
  if (!grid) return;

  const chambers = state.chambers || [];
  const status = state.assay_status || "idle";
  const finalReady = status === "finished";

  if (!chambers.length) {
    grid.innerHTML = "";
    setText("final-summary", "Waiting for chamber data.");
    return;
  }

  const positives = chambers.filter(ch => ch.final_call === "positive").length;
  const negatives = chambers.filter(ch => ch.final_call === "negative").length;
  const rejected = chambers.filter(ch => ch.final_call === "rejected").length;

  if (finalReady) {
    setText("final-summary", `${positives} positive, ${negatives} negative, ${rejected} rejected`);
  } else if (status === "stopped") {
    setText("final-summary", "Run stopped before final result.");
  } else {
    setText("final-summary", "Final calls update after the assay finishes.");
  }

  grid.innerHTML = "";
  for (const ch of chambers) {
    const call = ch.final_call || "pending";
    const tt = ch.tt_display_min == null ? "-" : `${ch.tt_display_min.toFixed(1)} min`;
    const completion = ch.completion_time == null ? "-" : `${ch.completion_time.toFixed(1)} min`;

    const card = document.createElement("div");
    card.className = `result-card ${call}`;
    card.innerHTML = `
      <div class="chamber">Chamber ${ch.chamber_id}</div>
      <div class="call">${formatResultCall(call)}</div>
      <div class="detail">Tt: ${tt}</div>
      <div class="detail">Completion: ${completion}</div>
      <div class="detail">Rejected segments: ${ch.rejected_segments || 0}</div>
    `;
    grid.appendChild(card);
  }
}

async function refreshState() {
  const state = await fetchJSON("/api/state");
  updateStateUI(state);
}

document.addEventListener("DOMContentLoaded", async () => {
  await loadProtocols();
  await refreshState();

  const select = document.getElementById("protocol-select");
  if (select) {
    select.addEventListener("change", toggleCustomProtocol);
  }

  ["custom-name", "custom-temp", "custom-time", "custom-warmup", "custom-interval"].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("input", updateProtocolSummary);
    }
  });

  setInterval(refreshState, 1500);
});
