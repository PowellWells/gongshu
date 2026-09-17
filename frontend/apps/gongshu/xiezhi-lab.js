(() => {
  "use strict";

  const title = document.querySelector("#xiezhiPreviewTitle");
  const copy = document.querySelector("#xiezhiPreviewCopy");
  const notice = document.querySelector("#notice");
  const actions = [...document.querySelectorAll("[data-xiezhi-action]")];
  const arenaEntry = document.querySelector('[data-xiezhi-entry="arena"]');
  const detailPanel = document.querySelector("#xiezhiDetailPanel");
  const detailTitle = document.querySelector("#xiezhiDetailTitle");
  const detailClose = document.querySelector("#xiezhiDetailClose");
  const panels = [...document.querySelectorAll("[data-xiezhi-panel]")];
  const historyList = document.querySelector("#xiezhiDecisionHistoryList");
  const runtimeStatus = document.querySelector("#xiezhiRuntimeStatus");
  const connectionStatus = document.querySelector("#xiezhiConnectionStatus");
  const runtimeContext = document.querySelector("#xiezhiRuntimeContext");
  const latestEvent = document.querySelector("#xiezhiLatestEvent");
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

  async function api(url) {
    const response = await fetch(url, { cache: "no-store" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.status === "error") {
      throw new Error(payload.message || `HTTP ${response.status}`);
    }
    return payload;
  }

  function eventLabel(value) {
    if (!value) return "无 NONE";
    const raw = String(value).toUpperCase();
    const english = raw.split("_").map((part) => (
      part.charAt(0) + part.slice(1).toLowerCase()
    )).join(" ");
    const translations = {
      EXECUTE_GRASP: "执行抓取",
      REOBSERVE: "重新观测",
      CHANGE_VIEWPOINT: "改变视角",
      RECOVER: "恢复",
      ABORT: "中止",
      NO_ACTION: "无动作",
    };
    return `${translations[raw] || ""} ${english}`.trim();
  }

  function statusLabel(value) {
    const raw = String(value || "UNKNOWN");
    const translations = {
      Prototype: "原型",
      Experimental: "实验中",
      Validated: "已验证",
      Archived: "已归档",
      SUCCESS: "成功",
      FAILED: "失败",
      UNKNOWN: "未知",
    };
    return `${translations[raw] || translations[raw.toUpperCase()] || ""} ${raw.replaceAll("_", " ")}`.trim();
  }

  function algorithmTypeLabel(value) {
    const translations = {
      "Xiezhi Algorithm": "獬豸算法",
      "External Baseline": "外部基线",
    };
    return `${translations[value] || ""} ${value || ""}`.trim() || "—";
  }

  function diagnosticLabel(value) {
    if (!value) return "—";
    const raw = String(value).toUpperCase();
    const translations = {
      HEURISTIC_UNCALIBRATED: "启发式未校准",
      LOW_GRASP_QUALITY: "抓取质量低",
      TARGET_MISMATCH: "目标不匹配",
      TARGET_EDGE: "目标位于边缘",
      INVALID_DEPTH: "深度无效",
      INVALID_DEPTH_SCALE: "深度尺度无效",
      ABNORMAL_SCALE: "尺度异常",
      GRIPPER_TOO_NARROW: "夹爪过窄",
      GRIPPER_TOO_WIDE: "夹爪过宽",
      LOW_GEOMETRY_CONFIDENCE: "几何置信度低",
      INSUFFICIENT_GEOMETRY: "几何信息不足",
      DEPTH_UNRELIABLE: "深度不可靠",
      PERCEPTION_UNCERTAIN: "感知不确定",
    };
    return `${translations[raw] || ""} ${raw.replaceAll("_", " ")}`.trim();
  }

  function reasonLabel(value) {
    if (!value) return "暂无决策证据 No decision evidence";
    const raw = String(value);
    const translations = {
      no_executable_grasp_candidate: "无可执行抓取候选",
      best_executable_ranked_candidate: "最佳可执行排序候选",
      provider_decision: "提供者决策",
    };
    return `${translations[raw] || ""} ${raw.replaceAll("_", " ")}`.trim();
  }

  function formatScore(value) {
    if (value === null || value === undefined || value === "") return "—";
    return Number.isFinite(Number(value)) ? Number(value).toFixed(3) : "—";
  }

  function formatUncertainty(values) {
    return (values || []).map(diagnosticLabel).join(" · ") || "无 NONE";
  }

  function formatDiagnostics(value) {
    if (!value || !Object.keys(value).length) return "无 NONE";
    return Object.entries(value).map(([key, item]) => {
      const rendered = typeof item === "object" ? JSON.stringify(item) : String(item);
      return `${key}: ${rendered}`;
    }).join(" · ");
  }

  function renderDecisionHistory(history) {
    if (!historyList) return;
    historyList.replaceChildren();
    if (!history?.length) {
      const empty = document.createElement("p");
      empty.className = "xiezhi-empty-state";
      empty.textContent = "暂无 Arena 结果记录 No Arena result records";
      historyList.append(empty);
      return;
    }
    history.forEach((entry) => {
      const decision = entry.decision_result || {};
      const validation = entry.validation_result || {};
      const row = document.createElement("div");
      row.className = "xiezhi-history-row";

      const decisionCell = document.createElement("span");
      const algorithm = document.createElement("small");
      algorithm.textContent = `${entry.algorithm?.algorithm_id || "—"} · ${entry.algorithm?.algorithm_version || "—"}`;
      const action = document.createElement("strong");
      action.textContent = `${eventLabel(decision.action)} · ${decision.selected_candidate_id || "无候选 NO CANDIDATE"}`;
      decisionCell.append(algorithm, action);

      const experimentCell = document.createElement("span");
      const experimentLabel = document.createElement("small");
      experimentLabel.textContent = "实验结果 Experiment Result";
      const experiment = document.createElement("b");
      experiment.textContent = `${entry.experiment_id || "—"} · ${entry.success ? "成功 SUCCESS" : `失败 FAILED${entry.failure_reason ? ` · ${entry.failure_reason}` : ""}`}`;
      experimentCell.append(experimentLabel, experiment);

      const validationCell = document.createElement("span");
      const validationLabel = document.createElement("small");
      validationLabel.textContent = `验证结果 Validation Result · ${entry.timestamp || "—"}`;
      const validationResult = document.createElement("b");
      validationResult.textContent = statusLabel(validation.status || validation.result || "UNKNOWN");
      validationCell.append(validationLabel, validationResult);

      row.append(decisionCell, experimentCell, validationCell);
      historyList.append(row);
    });
  }

  function renderDashboardState(state) {
    if (state.schema_version !== "gongshu.xiezhi-dashboard/v1") {
      throw new Error("unsupported XiezhiDashboardState schema");
    }
    const runtime = state.runtime || {};
    const engine = state.engine || {};
    const activeAlgorithm = state.active_algorithm || {};
    const evidence = state.evidence || {};
    const metadata = engine.algorithm_metadata || {};
    const blueprint = engine.blueprint || {};
    const pipeline = (blueprint.stages || []).map((stage) => (
      stage.name || stage.stage_id
    )).filter(Boolean).join(" → ");

    runtimeStatus.textContent = "就绪 READY";
    connectionStatus.textContent = `${activeAlgorithm.name || "—"} · ${activeAlgorithm.version || "—"}`;
    runtimeContext.textContent = eventLabel(runtime.current_action);
    latestEvent.textContent = runtime.selected_candidate || "无候选 NO CANDIDATE";

    setText("#xiezhiDecisionAlgorithm", activeAlgorithm.name || runtime.current_algorithm);
    setText("#xiezhiDecisionVersion", activeAlgorithm.version || runtime.algorithm_version);
    setText("#xiezhiDecisionAction", eventLabel(runtime.current_action));
    setText("#xiezhiDecisionCandidate", runtime.selected_candidate || "无 NONE");
    setText("#xiezhiDecisionConfidence", formatScore(runtime.confidence));
    setText("#xiezhiDecisionUncertainty", formatUncertainty(runtime.uncertainty));

    setText("#xiezhiEngineMetadata", [metadata.name, metadata.description, metadata.source].filter(Boolean).join(" · "));
    setText("#xiezhiActiveAlgorithmName", activeAlgorithm.name);
    setText("#xiezhiActiveAlgorithmVersion", activeAlgorithm.version);
    setText("#xiezhiActiveAlgorithmType", algorithmTypeLabel(activeAlgorithm.type));
    setText("#xiezhiActiveAlgorithmStatus", statusLabel(activeAlgorithm.status));
    setText("#xiezhiEngineType", algorithmTypeLabel(engine.algorithm_type));
    setText("#xiezhiEngineVersion", engine.algorithm_version);
    setText("#xiezhiEngineStatus", statusLabel(engine.algorithm_status));
    setText("#xiezhiEnginePipeline", pipeline || "未提供 NOT PROVIDED");
    setText("#xiezhiBlueprintReference", engine.blueprint_reference || "未绑定 NOT BOUND");

    setText("#xiezhiEvidenceCandidate", evidence.selected_candidate || "无 NONE");
    setText("#xiezhiEvidenceRisk", formatScore(evidence.risk_information?.value));
    setText("#xiezhiEvidenceUncertainty", formatUncertainty(evidence.uncertainty_information?.items));
    setText("#xiezhiEvidenceDiagnostics", formatDiagnostics(evidence.diagnostics));
    setText("#xiezhiEvidenceReason", reasonLabel(runtime.reason));
    renderDecisionHistory(state.history);
    window.dispatchEvent(new CustomEvent("xiezhi:dashboard-state", { detail: state }));
  }

  async function refreshDashboardState() {
    try {
      renderDashboardState(await api("/api/intelligence/dashboard"));
    } catch (_error) {
      runtimeStatus.textContent = "等待决策 WAITING FOR DECISION";
      connectionStatus.textContent = "AlgorithmDecision v1";
      runtimeContext.textContent = "不可用 NOT AVAILABLE";
      latestEvent.textContent = "无 NONE";
      window.dispatchEvent(new CustomEvent("xiezhi:dashboard-state", { detail: null }));
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
  arenaEntry?.addEventListener("click", () => {
    showNotice("算法竞技场 Algorithm Arena 入口已预留，本阶段未创建页面。", "success");
  });
  detailClose?.addEventListener("click", () => {
    detailPanel.hidden = true;
    actions.forEach((item) => {
      item.classList.remove("is-selected");
      item.setAttribute("aria-expanded", "false");
    });
  });

  window.addEventListener("gongshu:intelligence-state", refreshDashboardState);
  refreshDashboardState();
  window.setInterval(refreshDashboardState, 1000);
})();
