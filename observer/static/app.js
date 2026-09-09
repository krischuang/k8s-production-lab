const POLL_INTERVAL_MS = 3000;
const MAX_HISTORY = 10;

let knownPodNames = new Set();
let requestHistory = [];
let requestCounter = 0;

const POD_COLORS = ["#4f8cff", "#3fb950", "#d29922", "#f778ba", "#a371f7", "#39c5cf"];

function colorForPod(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return POD_COLORS[hash % POD_COLORS.length];
}

function shortPod(name) {
  const parts = name.split("-");
  return parts.length > 1 ? parts[parts.length - 1] : name;
}

function formatAge(seconds) {
  if (seconds === null || seconds === undefined) return "-";
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m${Math.floor(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h${Math.floor((seconds % 3600) / 60)}m`;
}

async function fetchJSON(url, opts) {
  const resp = await fetch(url, opts);
  if (!resp.ok) {
    const body = await resp.text().catch(() => "");
    throw new Error(`${url} -> HTTP ${resp.status} ${body}`.trim());
  }
  return resp.json();
}

function setPill(el, state, text) {
  el.className = `pill ${state}`;
  el.textContent = text;
}

async function refreshStatus() {
  try {
    const s = await fetchJSON("/api/status");
    const healthEl = document.getElementById("overall-health");
    if (s.healthy) setPill(healthEl, "healthy", "HEALTHY");
    else setPill(healthEl, "degraded", "DEGRADED");

    document.getElementById("app-version").textContent = s.version;
    document.getElementById("replica-summary").textContent =
      `${s.replicas.ready} Ready / ${s.replicas.desired} Desired`;
    document.getElementById("replica-detail").textContent =
      `${s.replicas.updated} updated / ${s.replicas.available} available`;

    document.getElementById("hpa-current").textContent = s.hpa.current ?? "-";
    document.getElementById("hpa-desired").textContent = s.hpa.desired ?? "-";
    document.getElementById("hpa-min").textContent = s.hpa.min ?? "-";
    document.getElementById("hpa-max").textContent = s.hpa.max ?? "-";
    document.getElementById("hpa-cpu").textContent =
      s.hpa.current_cpu_percent === null || s.hpa.current_cpu_percent === undefined
        ? "collecting metrics…"
        : `${s.hpa.current_cpu_percent}%`;
    document.getElementById("hpa-target").textContent = `${s.hpa.target_cpu_percent}%`;
  } catch (err) {
    setPill(document.getElementById("overall-health"), "error", "UNREACHABLE");
    console.error(err);
  }
}

function renderPods(pods) {
  const tbody = document.getElementById("pods-body");
  const currentNames = new Set(pods.map((p) => p.name));

  const removedNames = [...knownPodNames].filter((n) => !currentNames.has(n));

  tbody.innerHTML = "";
  for (const pod of pods.sort((a, b) => a.name.localeCompare(b.name))) {
    const tr = document.createElement("tr");
    tr.className = "pod-row";
    if (!knownPodNames.has(pod.name) && knownPodNames.size > 0) {
      tr.classList.add("pod-added");
    }
    tr.innerHTML = `
      <td>${pod.name}</td>
      <td><span class="badge ${pod.ready ? "ready" : "not-ready"}">${pod.ready ? "READY" : "NOT READY"}</span></td>
      <td>${pod.node}</td>
      <td>${pod.version}</td>
      <td>${pod.restarts}</td>
      <td>${formatAge(pod.age_seconds)}</td>
    `;
    tbody.appendChild(tr);
  }

  for (const name of removedNames) {
    const tr = document.createElement("tr");
    tr.className = "pod-row pod-removed";
    tr.innerHTML = `<td>${name}</td><td colspan="5"><em>removed by Kubernetes</em></td>`;
    tbody.prepend(tr);
    setTimeout(() => tr.remove(), 1600);
  }

  knownPodNames = currentNames;
}

async function refreshPods() {
  try {
    const data = await fetchJSON("/api/pods");
    renderPods(data.pods);
  } catch (err) {
    console.error(err);
  }
}

async function refreshDeployment() {
  try {
    const d = await fetchJSON("/api/deployment");
    const stateEl = document.getElementById("rollout-state");
    stateEl.textContent = d.rolling_out ? "Rollout in progress" : "Stable";
    stateEl.style.color = d.rolling_out ? "var(--amber)" : "var(--green)";

    document.getElementById("rollout-old").textContent = d.healthy_old_replicas;
    document.getElementById("rollout-new").textContent = d.new_replicas;
    document.getElementById("rollout-new-ready").textContent = d.ready_new_replicas;

    const serviceEl = document.getElementById("rollout-service");
    serviceEl.textContent = d.service_available ? "Still Available" : "UNAVAILABLE";
    serviceEl.style.color = d.service_available ? "var(--green)" : "var(--red)";

    const reasonBox = document.getElementById("rollout-reason-box");
    if (d.reason) {
      reasonBox.style.display = "block";
      document.getElementById("rollout-reason").textContent = d.reason;
    } else {
      reasonBox.style.display = "none";
    }
  } catch (err) {
    console.error(err);
  }
}

function addHistoryEntry(entry) {
  requestCounter += 1;
  requestHistory.unshift({ ...entry, id: requestCounter });
  requestHistory = requestHistory.slice(0, MAX_HISTORY);

  const log = document.getElementById("request-log");
  log.innerHTML = "";
  for (const item of requestHistory) {
    const div = document.createElement("div");
    if (item.error) {
      div.className = "entry error";
      div.innerHTML = `<span>Request ${item.id}</span><span class="pod-chip">error</span>`;
      div.title = item.error;
    } else {
      div.className = "entry";
      const color = colorForPod(item.pod);
      div.innerHTML = `
        <span>Request ${item.id} &rarr; ${shortPod(item.pod)} <span style="color:var(--text-dim)">(${item.node})</span></span>
        <span class="pod-chip" style="background:${color}">${item.latency_ms}ms</span>
      `;
    }
    log.appendChild(div);
  }
}

async function sendRequest() {
  const btn = document.getElementById("send-request-btn");
  btn.disabled = true;
  try {
    const data = await fetchJSON("/api/route-request", { method: "POST" });
    addHistoryEntry(data);
  } catch (err) {
    addHistoryEntry({ error: err.message });
  } finally {
    btn.disabled = false;
  }
}

document.getElementById("send-request-btn").addEventListener("click", sendRequest);

function tick() {
  refreshStatus();
  refreshPods();
  refreshDeployment();
}

tick();
setInterval(tick, POLL_INTERVAL_MS);
