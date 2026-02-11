const state = {
  runs: [],
  selectedRunId: null,
  run: null,
  logs: [],
  eventSource: null,
};

const els = {
  startForm: document.getElementById("start-form"),
  modeSelect: document.getElementById("mode-select"),
  dryRunSelect: document.getElementById("dry-run-select"),
  configPath: document.getElementById("config-path"),
  weeklyConfigPath: document.getElementById("weekly-config-path"),
  maxArticles: document.getElementById("max-articles"),
  hours: document.getElementById("hours"),
  formMessage: document.getElementById("form-message"),
  runsTableBody: document.getElementById("runs-table-body"),
  runSummary: document.getElementById("run-summary"),
  progressBar: document.getElementById("progress-bar"),
  statsGrid: document.getElementById("stats-grid"),
  logsView: document.getElementById("logs-view"),
  levelFilter: document.getElementById("level-filter"),
  textFilter: document.getElementById("text-filter"),
  rerunBtn: document.getElementById("rerun-btn"),
  deleteBtn: document.getElementById("delete-btn"),
  deleteArtifactBtn: document.getElementById("delete-artifact-btn"),
  previewBtn: document.getElementById("preview-btn"),
  refreshRunsBtn: document.getElementById("refresh-runs-btn"),
  artifactPath: document.getElementById("artifact-path"),
  artifactContent: document.getElementById("artifact-content"),
};

function formatTime(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

async function requestJSON(url, options = {}) {
  const resp = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  let payload = {};
  try {
    payload = await resp.json();
  } catch (err) {
    payload = {};
  }

  if (!resp.ok) {
    const detail = payload.detail || `请求失败: ${resp.status}`;
    throw new Error(detail);
  }

  return payload;
}

function setFormMessage(text, isError = false) {
  els.formMessage.textContent = text;
  els.formMessage.style.color = isError ? "#b42318" : "#1d7874";
}

function statusClass(status) {
  const normalized = (status || "unknown").toLowerCase();
  if (["queued", "running", "success", "failed"].includes(normalized)) {
    return normalized;
  }
  return "queued";
}

function normalizeStatus(status) {
  const mapping = {
    queued: "排队中",
    running: "运行中",
    success: "成功",
    failed: "失败",
    cancelled: "取消",
  };
  return mapping[status] || status || "-";
}

function renderRunsTable() {
  const rows = state.runs.map((run) => {
    const tr = document.createElement("tr");
    if (run.id === state.selectedRunId) {
      tr.classList.add("active");
    }
    tr.addEventListener("click", () => {
      selectRun(run.id);
    });

    tr.innerHTML = `
      <td>#${run.id}</td>
      <td>${run.mode}</td>
      <td><span class="status-pill ${statusClass(run.status)}">${normalizeStatus(run.status)}</span></td>
      <td>${run.current_step || "-"}</td>
      <td>${formatTime(run.started_at)}</td>
    `;
    return tr;
  });

  els.runsTableBody.innerHTML = "";
  rows.forEach((row) => els.runsTableBody.appendChild(row));
}

function renderStats(run) {
  els.statsGrid.innerHTML = "";
  const stats = run?.stats || {};
  const chips = [];

  if (stats.unique_articles !== undefined) {
    chips.push(`唯一文章 ${stats.unique_articles}`);
  }
  if (stats.filtered_articles !== undefined) {
    chips.push(`过滤后 ${stats.filtered_articles}`);
  }
  if (stats.ai_total !== undefined) {
    chips.push(`AI 成功 ${stats.ai_success || 0}/${stats.ai_total}`);
  }
  if (stats.dedup_written !== undefined) {
    chips.push(`写入去重 ${stats.dedup_written}`);
  }

  if (stats.categories && typeof stats.categories === "object") {
    Object.entries(stats.categories).forEach(([name, count]) => {
      chips.push(`${name} ${count}`);
    });
  }

  chips.forEach((text) => {
    const node = document.createElement("span");
    node.className = "stat-chip";
    node.textContent = text;
    els.statsGrid.appendChild(node);
  });
}

function renderRunSummary() {
  const run = state.run;
  if (!run) {
    els.runSummary.classList.add("empty");
    els.runSummary.innerHTML = "请选择或启动一个任务";
    els.progressBar.style.width = "0%";
    renderStats(null);
    toggleActions(false, false);
    return;
  }

  els.runSummary.classList.remove("empty");
  const duration = run.duration_seconds ? `${run.duration_seconds.toFixed(1)}s` : "-";
  const output = run.output_path || "-";

  els.runSummary.innerHTML = `
    <div><strong>运行 #${run.id}</strong> · ${run.mode}</div>
    <div>状态：${normalizeStatus(run.status)} · 进度：${run.progress || 0}%</div>
    <div>阶段：${run.current_step || "-"}</div>
    <div>开始：${formatTime(run.started_at)}</div>
    <div>结束：${formatTime(run.ended_at)}</div>
    <div>耗时：${duration}</div>
    <div>产物：${output}</div>
    ${run.error_message ? `<div style="color:#b42318;">错误：${run.error_message}</div>` : ""}
  `;

  const progress = Math.max(0, Math.min(100, Number(run.progress || 0)));
  els.progressBar.style.width = `${progress}%`;
  renderStats(run);
  toggleActions(true, Boolean(run.output_path));
}

function toggleActions(runSelected, hasArtifact) {
  els.rerunBtn.disabled = !runSelected;
  els.deleteBtn.disabled = !runSelected;
  els.deleteArtifactBtn.disabled = !runSelected;
  els.previewBtn.disabled = !runSelected || !hasArtifact;
}

function renderLogs() {
  const levelFilter = els.levelFilter.value;
  const textFilter = els.textFilter.value.trim().toLowerCase();

  const filtered = state.logs.filter((log) => {
    const levelOk = levelFilter === "ALL" || log.level === levelFilter;
    const textOk = !textFilter || (log.message || "").toLowerCase().includes(textFilter);
    return levelOk && textOk;
  });

  const fragment = document.createDocumentFragment();
  filtered.forEach((log) => {
    const line = document.createElement("div");
    line.className = `log-line ${(log.level || "").toLowerCase()}`;

    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = `[${log.timestamp}] [${log.level}] [${log.module}]`;

    const message = document.createElement("span");
    message.textContent = ` ${log.message || ""}`;

    line.appendChild(meta);
    line.appendChild(message);
    fragment.appendChild(line);
  });

  const shouldStick = els.logsView.scrollTop + els.logsView.clientHeight >= els.logsView.scrollHeight - 40;

  els.logsView.innerHTML = "";
  els.logsView.appendChild(fragment);

  if (shouldStick) {
    els.logsView.scrollTop = els.logsView.scrollHeight;
  }
}

function appendLog(log) {
  state.logs.push(log);
  if (state.logs.length > 3000) {
    state.logs = state.logs.slice(-3000);
  }
  renderLogs();
}

function closeEventSource() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
}

function connectRunEvents(runId) {
  closeEventSource();

  const stream = new EventSource(`/api/runs/${runId}/events`);
  stream.onmessage = (event) => {
    if (!event.data) {
      return;
    }

    let payload = {};
    try {
      payload = JSON.parse(event.data);
    } catch (err) {
      return;
    }

    if (payload.type === "log") {
      appendLog(payload.data);
      return;
    }

    if (payload.type === "run") {
      state.run = payload.data;
      renderRunSummary();
      loadRuns(false);
      return;
    }

    if (payload.type === "done") {
      loadRuns(false);
      return;
    }

    if (payload.type === "deleted") {
      state.run = null;
      state.logs = [];
      renderRunSummary();
      renderLogs();
      loadRuns(false);
    }
  };

  stream.onerror = () => {
    if (state.run && ["success", "failed", "cancelled"].includes(state.run.status)) {
      closeEventSource();
    }
  };

  state.eventSource = stream;
}

async function loadRuns(selectLatest = false) {
  const payload = await requestJSON("/api/runs?limit=200");
  state.runs = payload.runs || [];
  renderRunsTable();

  if (selectLatest && state.runs.length > 0) {
    selectRun(state.runs[0].id);
  }
}

async function loadRun(runId) {
  const payload = await requestJSON(`/api/runs/${runId}`);
  state.run = payload.run;
  renderRunSummary();
}

async function loadLogs(runId) {
  const payload = await requestJSON(`/api/runs/${runId}/logs?after_id=0&limit=2000`);
  state.logs = payload.logs || [];
  renderLogs();
}

async function selectRun(runId) {
  state.selectedRunId = runId;
  renderRunsTable();
  await loadRun(runId);
  await loadLogs(runId);
  connectRunEvents(runId);
}

async function startRun(event) {
  event.preventDefault();
  setFormMessage("正在提交任务...");

  const payload = {
    mode: els.modeSelect.value,
    dry_run: els.dryRunSelect.value === "true",
    config_path: els.configPath.value,
    weekly_config_path: els.weeklyConfigPath.value,
    max_articles: els.maxArticles.value ? Number(els.maxArticles.value) : null,
    hours: els.hours.value ? Number(els.hours.value) : null,
    extra_args: [],
  };

  try {
    const result = await requestJSON("/api/runs", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setFormMessage(`任务 #${result.run_id} 已启动`);
    await loadRuns(false);
    await selectRun(result.run_id);
  } catch (err) {
    setFormMessage(err.message, true);
  }
}

async function rerunSelected() {
  if (!state.selectedRunId) {
    return;
  }

  try {
    const result = await requestJSON(`/api/runs/${state.selectedRunId}/rerun`, {
      method: "POST",
    });
    setFormMessage(`已重跑，新的任务 #${result.run_id}`);
    await loadRuns(false);
    await selectRun(result.run_id);
  } catch (err) {
    setFormMessage(err.message, true);
  }
}

async function deleteSelected(deleteArtifact) {
  if (!state.selectedRunId) {
    return;
  }

  const actionText = deleteArtifact ? "删除记录和产物" : "删除记录";
  if (!window.confirm(`确认${actionText}吗？`)) {
    return;
  }

  try {
    await requestJSON(`/api/runs/${state.selectedRunId}?delete_artifact=${deleteArtifact}`, {
      method: "DELETE",
    });

    setFormMessage(`已${actionText}`);
    state.selectedRunId = null;
    state.run = null;
    state.logs = [];
    renderRunSummary();
    renderLogs();
    els.artifactPath.textContent = "";
    els.artifactContent.textContent = "暂无产物";
    closeEventSource();
    await loadRuns(true);
  } catch (err) {
    setFormMessage(err.message, true);
  }
}

async function previewArtifact() {
  if (!state.selectedRunId) {
    return;
  }

  try {
    const payload = await requestJSON(`/api/runs/${state.selectedRunId}/artifact`);
    els.artifactPath.textContent = payload.path;
    els.artifactContent.textContent = payload.content || "文件为空";
    if (payload.truncated) {
      els.artifactContent.textContent += "\n\n---\n内容过长，已截断显示。";
    }
  } catch (err) {
    setFormMessage(err.message, true);
  }
}

function startAutoRefresh() {
  window.setInterval(async () => {
    try {
      await loadRuns(false);
      if (state.selectedRunId && state.run && ["success", "failed", "cancelled"].includes(state.run.status)) {
        await loadRun(state.selectedRunId);
      }
    } catch (err) {
      // Ignore transient polling failures.
    }
  }, 8000);
}

function bindEvents() {
  els.startForm.addEventListener("submit", startRun);
  els.levelFilter.addEventListener("change", renderLogs);
  els.textFilter.addEventListener("input", renderLogs);
  els.rerunBtn.addEventListener("click", rerunSelected);
  els.deleteBtn.addEventListener("click", () => deleteSelected(false));
  els.deleteArtifactBtn.addEventListener("click", () => deleteSelected(true));
  els.previewBtn.addEventListener("click", previewArtifact);
  els.refreshRunsBtn.addEventListener("click", () => loadRuns(false));

  window.addEventListener("beforeunload", () => {
    closeEventSource();
  });
}

async function boot() {
  bindEvents();
  renderRunSummary();
  renderLogs();

  try {
    await loadRuns(true);
  } catch (err) {
    setFormMessage(err.message, true);
  }

  startAutoRefresh();
}

boot();
