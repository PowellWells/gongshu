(() => {
  "use strict";

  const title = document.querySelector("#xiezhiPreviewTitle");
  const copy = document.querySelector("#xiezhiPreviewCopy");
  const notice = document.querySelector("#notice");
  const actions = [...document.querySelectorAll("[data-xiezhi-action]")];
  const detailPanel = document.querySelector("#xiezhiDetailPanel");
  const detailTitle = document.querySelector("#xiezhiDetailTitle");
  const detailClose = document.querySelector("#xiezhiDetailClose");
  const panels = [...document.querySelectorAll("[data-xiezhi-panel]")];
  const providerList = document.querySelector("#xiezhiProviderList");
  const historyList = document.querySelector("#xiezhiDecisionHistoryList");
  const runtimeStatus = document.querySelector("#xiezhiRuntimeStatus");
  const connectionStatus = document.querySelector("#xiezhiConnectionStatus");
  const runtimeContext = document.querySelector("#xiezhiRuntimeContext");
  const latestEvent = document.querySelector("#xiezhiLatestEvent");
  let intelligenceState = null;
  let noticeTimer = 0;

  if (!title || !copy || !notice || !actions.length || !detailPanel) return;

  function setText(selector, value) {
    const element = document.querySelector(selector);
    if (element) element.textContent = value ?? "—";
  }

  function showNotice(message, type = "success") {
    window.clearTimeout(noticeTimer);
    notice.textContent = message;
    notice.className = `workspace-notice is-${type}`;
    notice.hidden = false;
    noticeTimer = window.setTimeout(() => { notice.hidden = true; }, 4200);
  }

  async function api(url, options = {}) {
    const response = await fetch(url, { cache: "no-store", ...options });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.status === "error") {
      throw new Error(payload.message || `HTTP ${response.status}`);
    }
    return payload;
  }

  const apiPost = (url, body) => api(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  function eventLabel(value) {
    if (!value) return "NONE";
    return String(value).split("_").map((part) => (
      part.charAt(0).toUpperCase() + part.slice(1).toLowerCase()
    )).join(" ");
  }

  function formatScore(value) {
    return Number.isFinite(Number(value)) ? Number(value).toFixed(3) : "—";
  }

  function engineLabel(provider, algorithm) {
    const name = provider === "xiezhi" ? "Xiezhi" : "Gongshu Baseline";
    return `${name} · ${algorithm || "UNKNOWN"}`;
  }

  function renderDecisionHistory(history) {
    if (!historyList) return;
    historyList.replaceChildren();
    if (!history?.length) {
      const empty = document.createElement("p");
      empty.className = "xiezhi-empty-state";
      empty.textContent = "尚无决策记录 No decisions yet";
      historyList.append(empty);
      return;
    }
    history.forEach((decision) => {
      const row = document.createElement("div");
      row.className = "xiezhi-history-row";
      row.innerHTML = `
        <span><small>${decision.provider} · ${decision.algorithm}</small>
        <strong>${eventLabel(decision.selected_action)}</strong></span>
        <span><small>${decision.selected_candidate_id || "NO CANDIDATE"}</small>
        <b>${formatScore(decision.confidence)}</b></span>`;
      historyList.append(row);
    });
  }

  function renderDecisionEngines(state) {
    if (!providerList) return;
    providerList.replaceChildren();
    (state.available_algorithms || []).forEach((entry) => {
      const selected = entry.provider === state.selected_provider
        && entry.algorithm === state.selected_algorithm;
      const active = entry.provider === state.active_provider
        && entry.algorithm === state.algorithm;
      const button = document.createElement("button");
      button.type = "button";
      button.className = `xiezhi-provider-option${selected ? " is-selected" : ""}`;
      button.disabled = selected;
      button.innerHTML = `
        <span><small>${entry.provider === "xiezhi" ? "XIEZHI ENGINE" : "BASELINE ENGINE"}</small>
        <strong>${entry.algorithm}</strong></span>
        <b>${active ? "ACTIVE" : selected ? "SELECTED" : "USE ENGINE"}</b>`;
      button.addEventListener("click", async () => {
        const hadDecision = Boolean(intelligenceState?.decision_available);
        try {
          let next = await apiPost("/api/intelligence/select-algorithm", entry);
          if (hadDecision) next = await apiPost("/api/intelligence/decide", {});
          renderRuntimeState(next);
          showNotice(`决策引擎已切换：${engineLabel(entry.provider, entry.algorithm)}`);
        } catch (error) {
          showNotice(`决策引擎切换失败：${error.message}`, "error");
        }
      });
      providerList.append(button);
    });
  }

  function renderRuntimeState(state) {
    intelligenceState = state;
    runtimeStatus.textContent = String(state.status || "unknown").toUpperCase();
    connectionStatus.textContent = engineLabel(state.active_provider, state.algorithm);
    runtimeContext.textContent = state.decision_available ? "AVAILABLE" : "NOT AVAILABLE";
    const decision = state.last_decision;
    latestEvent.textContent = decision
      ? `${eventLabel(decision.selected_action)} · ${decision.selected_candidate_id || decision.reason}`
      : "NONE";

    setText("#xiezhiDecisionProvider", engineLabel(decision?.provider || state.active_provider, decision?.algorithm || state.algorithm));
    setText("#xiezhiDecisionAlgorithm", decision?.algorithm || state.selected_algorithm);
    setText("#xiezhiDecisionStatus", decision?.status || "NOT AVAILABLE");
    setText("#xiezhiDecisionAction", eventLabel(decision?.selected_action));
    setText("#xiezhiDecisionCandidate", decision?.selected_candidate_id || "NONE");
    setText("#xiezhiDecisionReason", decision?.reason || "等待一次抓取规划 Waiting for planning");

    const diagnostics = decision?.diagnostics || {};
    setText("#xiezhiEvidenceConfidence", formatScore(decision?.confidence));
    setText("#xiezhiEvidenceRisk", formatScore(decision?.risk_estimation));
    setText("#xiezhiEvidenceType", diagnostics.provider_score_type || decision?.confidence_type || "—");
    setText("#xiezhiEvidencePlannerScore", formatScore(diagnostics.planner_ranking_score));
    setText("#xiezhiEvidenceReason", decision?.reason || "暂无决策证据");
    setText("#xiezhiEvidenceUncertainty", (diagnostics.uncertainty_reasons || []).join(", ") || "NONE");
    renderDecisionEngines(state);
    renderDecisionHistory(state.decision_history);
  }

  async function refreshRuntimeStatus() {
    try {
      renderRuntimeState(await api("/api/intelligence/state"));
    } catch (_error) {
      runtimeStatus.textContent = "UNAVAILABLE";
      connectionStatus.textContent = "OFFLINE";
    }
  }

  function openPanel(button) {
    const selectedPanel = button.dataset.xiezhiAction;
    actions.forEach((item) => {
      const selected = item === button;
      item.classList.toggle("is-selected", selected);
      item.setAttribute("aria-expanded", String(selected));
    });
    panels.forEach((panel) => { panel.hidden = panel.dataset.xiezhiPanel !== selectedPanel; });
    title.textContent = button.dataset.preview;
    copy.textContent = button.dataset.copy;
    detailTitle.textContent = button.dataset.preview;
    detailPanel.hidden = false;
    detailPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  actions.forEach((button) => button.addEventListener("click", () => openPanel(button)));
  detailClose?.addEventListener("click", () => {
    detailPanel.hidden = true;
    actions.forEach((item) => {
      item.classList.remove("is-selected");
      item.setAttribute("aria-expanded", "false");
    });
  });

  window.addEventListener("gongshu:intelligence-state", (event) => {
    if (event.detail) renderRuntimeState(event.detail);
  });
  refreshRuntimeStatus();
  window.setInterval(refreshRuntimeStatus, 1000);
})();
