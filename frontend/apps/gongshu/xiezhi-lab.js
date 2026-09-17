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
  const availableAlgorithmList = document.querySelector("#xiezhiAvailableAlgorithms");
  const applyAlgorithmButton = document.querySelector("#xiezhiApplyAlgorithm");
  const algorithmSwitchStatus = document.querySelector("#xiezhiAlgorithmSwitchStatus");
  const algorithmCount = document.querySelector("#xiezhiAlgorithmCount");
  let noticeTimer = 0;
  let selectedAlgorithm = null;
  let latestIntelligenceState = null;
  let latestDashboardState = null;
  let switchInFlight = false;

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

  async function apiPost(url, body) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
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

  function algorithmIdentity(entry) {
    const provider = String(entry?.provider || "").trim();
    const algorithmId = String(entry?.algorithm_id || entry?.algorithm || "").trim();
    return {
      provider,
      algorithmId,
      key: `${provider}/${algorithmId}`,
      name: entry?.name || entry?.display_name || algorithmId.replaceAll("_", " ") || "—",
      version: entry?.version || "未声明 UNDECLARED",
      type: entry?.type || "未分类 UNCLASSIFIED",
      status: entry?.status || "",
    };
  }

  function renderActiveAlgorithm(activeAlgorithm) {
    setText("#xiezhiActiveAlgorithmName", activeAlgorithm?.name);
    setText("#xiezhiActiveAlgorithmVersion", activeAlgorithm?.version);
    setText("#xiezhiActiveAlgorithmType", algorithmTypeLabel(activeAlgorithm?.type));
    setText("#xiezhiActiveAlgorithmStatus", statusLabel(activeAlgorithm?.status));
    setText(
      "#xiezhiActiveAlgorithmIndicator",
      activeAlgorithm?.algorithm_id ? "已激活 ACTIVE" : "等待状态 WAITING",
    );
    if (activeAlgorithm?.name || activeAlgorithm?.version) {
      connectionStatus.textContent = `${activeAlgorithm?.name || "—"} · ${activeAlgorithm?.version || "—"}`;
    }
  }

  function renderAlgorithmManager(state) {
    latestIntelligenceState = state;
    const active = state?.active_algorithm || {};
    const activeIdentity = algorithmIdentity(active);
    const algorithms = (state?.available_algorithms || [])
      .map(algorithmIdentity)
      .filter((entry) => entry.provider && entry.algorithmId);

    if (selectedAlgorithm?.key === activeIdentity.key) selectedAlgorithm = null;
    renderActiveAlgorithm(active);
    if (algorithmCount) algorithmCount.textContent = `${algorithms.length} ALGORITHMS`;
    if (!availableAlgorithmList || !applyAlgorithmButton || !algorithmSwitchStatus) return;

    availableAlgorithmList.replaceChildren();
    if (!algorithms.length) {
      const empty = document.createElement("p");
      empty.className = "xiezhi-empty-state";
      empty.textContent = "暂无可用算法 NO AVAILABLE ALGORITHMS";
      availableAlgorithmList.append(empty);
    }

    algorithms.forEach((algorithm) => {
      const isActive = algorithm.key === activeIdentity.key;
      const isSelected = algorithm.key === selectedAlgorithm?.key;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "xiezhi-provider-option";
      button.classList.toggle("is-active", isActive);
      button.classList.toggle("is-selected", isSelected);
      button.dataset.provider = algorithm.provider;
      button.dataset.algorithmId = algorithm.algorithmId;
      button.setAttribute("role", "radio");
      button.setAttribute("aria-checked", String(isSelected || (!selectedAlgorithm && isActive)));
      button.disabled = switchInFlight || isActive;

      const identity = document.createElement("span");
      const metadata = document.createElement("small");
      metadata.textContent = `${algorithm.version} · ${algorithmTypeLabel(algorithm.type)}`;
      const name = document.createElement("strong");
      name.textContent = algorithm.name;
      identity.append(metadata, name);

      const stateLabel = document.createElement("b");
      stateLabel.textContent = isActive
        ? "当前 ACTIVE"
        : (isSelected ? "已选择 SELECTED" : "选择 SELECT");
      button.append(identity, stateLabel);
      button.addEventListener("click", () => {
        selectedAlgorithm = algorithm;
        renderAlgorithmManager(latestIntelligenceState);
      });
      availableAlgorithmList.append(button);
    });

    applyAlgorithmButton.disabled = switchInFlight || !selectedAlgorithm;
    algorithmSwitchStatus.textContent = switchInFlight
      ? "正在切换 SWITCHING"
      : (selectedAlgorithm
        ? `${selectedAlgorithm.name} · 待应用 READY TO APPLY`
        : "当前算法已生效 ACTIVE ALGORITHM APPLIED");
  }

  function renderDecisionWaiting(activeAlgorithm) {
    runtimeStatus.textContent = "等待决策 WAITING FOR DECISION";
    renderActiveAlgorithm(activeAlgorithm);
    runtimeContext.textContent = "不可用 NOT AVAILABLE";
    latestEvent.textContent = "无 NONE";
    setText("#xiezhiDecisionAlgorithm", activeAlgorithm?.name);
    setText("#xiezhiDecisionVersion", activeAlgorithm?.version);
    setText("#xiezhiDecisionAction", "无 NONE");
    setText("#xiezhiDecisionCandidate", "无 NONE");
    setText("#xiezhiDecisionConfidence", "—");
    setText("#xiezhiDecisionUncertainty", "无 NONE");
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

    latestDashboardState = state;
    renderActiveAlgorithm(activeAlgorithm);
    runtimeStatus.textContent = "就绪 READY";
    runtimeContext.textContent = eventLabel(runtime.current_action);
    latestEvent.textContent = runtime.selected_candidate || "无候选 NO CANDIDATE";

    setText("#xiezhiDecisionAlgorithm", activeAlgorithm.name || runtime.current_algorithm);
    setText("#xiezhiDecisionVersion", activeAlgorithm.version || runtime.algorithm_version);
    setText("#xiezhiDecisionAction", eventLabel(runtime.current_action));
    setText("#xiezhiDecisionCandidate", runtime.selected_candidate || "无 NONE");
    setText("#xiezhiDecisionConfidence", formatScore(runtime.confidence));
    setText("#xiezhiDecisionUncertainty", formatUncertainty(runtime.uncertainty));

    setText("#xiezhiEngineMetadata", [metadata.name, metadata.description, metadata.source].filter(Boolean).join(" · "));
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
    let intelligenceState = latestIntelligenceState;
    try {
      intelligenceState = await api("/api/intelligence/state");
      renderAlgorithmManager(intelligenceState);
    } catch (_error) {
      if (algorithmSwitchStatus) algorithmSwitchStatus.textContent = "注册表不可用 REGISTRY UNAVAILABLE";
    }
    try {
      renderDashboardState(await api("/api/intelligence/dashboard"));
    } catch (_error) {
      latestDashboardState = null;
      renderDecisionWaiting(intelligenceState?.active_algorithm);
      window.dispatchEvent(new CustomEvent("xiezhi:dashboard-state", { detail: null }));
    }
  }

  async function applySelectedAlgorithm() {
    if (!selectedAlgorithm || switchInFlight) return;
    const target = selectedAlgorithm;
    const refreshDecision = Boolean(latestDashboardState);
    let switchFailed = false;
    switchInFlight = true;
    renderAlgorithmManager(latestIntelligenceState);
    try {
      const switchedState = await apiPost("/api/intelligence/select-algorithm", {
        provider: target.provider,
        algorithm: target.algorithmId,
      });
      selectedAlgorithm = null;
      renderAlgorithmManager(switchedState);
      renderDecisionWaiting(switchedState.active_algorithm);
      if (refreshDecision) {
        try {
          await apiPost("/api/intelligence/decide", {});
        } catch (_error) {
          // A new decision will be generated after the next completed candidate pool.
        }
      }
      await refreshDashboardState();
      showNotice(`算法已切换 Algorithm switched · ${target.name}`, "success");
      window.dispatchEvent(new CustomEvent("xiezhi:algorithm-changed", {
        detail: switchedState.active_algorithm,
      }));
    } catch (error) {
      switchFailed = true;
      if (algorithmSwitchStatus) algorithmSwitchStatus.textContent = "切换失败 SWITCH FAILED";
      showNotice(`算法切换失败 Algorithm switch failed · ${error.message}`, "error");
    } finally {
      switchInFlight = false;
      renderAlgorithmManager(latestIntelligenceState);
      if (switchFailed && algorithmSwitchStatus) {
        algorithmSwitchStatus.textContent = "切换失败 SWITCH FAILED";
      }
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
  applyAlgorithmButton?.addEventListener("click", applySelectedAlgorithm);
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
  window.setInterval(() => {
    if (!switchInFlight) refreshDashboardState();
  }, 1000);
})();
