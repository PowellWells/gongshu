(() => {
  "use strict";

  const CAMERA_SCHEMA_VERSION = "vision2grasp.camera/v1";
  const TARGET_PERCEPTION_SCHEMA_VERSION = "gongshu.target-perception/v1";
  const RUN_SCHEMA_VERSION = "vision2grasp.run/v1";
  const PUBLISHED_SCHEMA_VERSION = "vision2grasp.launcher/v1";
  const PUBLISHED_MANIFEST_URL = "../../runtime/latest.json";
  const { PipelineStateMachine, canStartGrasp } = window.GongshuPipeline;

  const PIPELINE_MESSAGES = Object.freeze({
    LIVE: "实时视觉已就绪，等待真实输入",
    TARGET_SELECTED: "已接收真实目标选择",
    SCENE_CAPTURED: "已获取真实 RGB 场景快照",
    SPATIAL_ANALYSIS: "空间分析模块未接入 · WAITING",
    GRASP_PLANNING: "抓取规划模块未接入 · WAITING",
    SCENE_SYNC: "等待真实场景同步 · WAITING",
    SIMULATION: "仿真验证进行中",
    VERIFIED: "已载入真实离线运行产物",
    RESET: "正在重置流程",
  });

  const VIEW_LABELS = Object.freeze({
    live: "Live RGB",
    spatial: "Spatial Perception",
    grasp: "Grasp Planning",
    simulation: "MuJoCo Validation",
  });

  const SOURCE_LABELS = Object.freeze({
    phone: "手机 Phone",
    usb: "USB 相机 USB Camera",
    network: "网络流 Network Stream",
    rgbd: "RGB-D 相机 RGB-D Camera",
  });

  const byId = (id) => document.getElementById(id);
  const els = {
    pipelineBadge: byId("pipelineBadge"),
    pipelineMessage: byId("pipelineMessage"),
    sourceSelect: byId("sourceSelect"),
    conditionSelect: byId("conditionSelect"),
    robotSelect: byId("robotSelect"),
    viewModeSelect: byId("viewModeSelect"),
    analyzeTargetsButton: byId("analyzeTargetsButton"),
    startGraspButton: byId("startGraspButton"),
    startGraspLabel: byId("startGraspLabel"),
    startGraspHint: byId("startGraspHint"),
    resetPipelineButton: byId("resetPipelineButton"),
    liveState: byId("liveState"),
    liveEmpty: byId("liveEmpty"),
    liveMedia: byId("liveMedia"),
    targetOverlay: byId("targetOverlay"),
    analysisControls: byId("analysisControls"),
    analysisStatus: byId("analysisStatus"),
    resumeLiveButton: byId("resumeLiveButton"),
    liveSourceLabel: byId("liveSourceLabel"),
    liveResolution: byId("liveResolution"),
    liveConnection: byId("liveConnection"),
    spatialState: byId("spatialState"),
    spatialSnapshot: byId("spatialSnapshot"),
    spatialEmpty: byId("spatialEmpty"),
    spatialPendingOverlay: byId("spatialPendingOverlay"),
    spatialFooter: byId("spatialFooter"),
    graspState: byId("graspState"),
    graspMedia: byId("graspMedia"),
    graspEmpty: byId("graspEmpty"),
    graspFooter: byId("graspFooter"),
    simulationState: byId("simulationState"),
    simulationMedia: byId("simulationMedia"),
    simulationEmpty: byId("simulationEmpty"),
    simulationFooter: byId("simulationFooter"),
    targetStatus: byId("targetStatus"),
    targetValue: byId("targetValue"),
    targetClassValue: byId("targetClassValue"),
    targetConfidenceValue: byId("targetConfidenceValue"),
    targetLockValue: byId("targetLockValue"),
    targetDetail: byId("targetDetail"),
    spatialInspectorStatus: byId("spatialInspectorStatus"),
    spatialValue: byId("spatialValue"),
    spatialDetail: byId("spatialDetail"),
    graspInspectorStatus: byId("graspInspectorStatus"),
    graspValue: byId("graspValue"),
    graspDetail: byId("graspDetail"),
    systemStatus: byId("systemStatus"),
    statusConnection: byId("statusConnection"),
    statusViewMode: byId("statusViewMode"),
    statusPrimaryView: byId("statusPrimaryView"),
    statusSnapshot: byId("statusSnapshot"),
    notice: byId("notice"),
    cameraSetupButton: byId("cameraSetupButton"),
    cameraSetupDialog: byId("cameraSetupDialog"),
    cameraConnectionState: byId("cameraConnectionState"),
    cameraDevice: byId("cameraDevice"),
    cameraConnection: byId("cameraConnection"),
    cameraMode: byId("cameraMode"),
    cameraSideResolution: byId("cameraSideResolution"),
    cameraSideFps: byId("cameraSideFps"),
    cameraSideLatency: byId("cameraSideLatency"),
    pairingState: byId("pairingState"),
    pairingQr: byId("pairingQr"),
    cameraLanAddress: byId("cameraLanAddress"),
    pairedDevice: byId("pairedDevice"),
    refreshPairingButton: byId("refreshPairingButton"),
    captureResolution: byId("captureResolution"),
    captureEmpty: byId("captureEmpty"),
    captureImage: byId("captureImage"),
    captureStatus: byId("captureStatus"),
    saveCaptureButton: byId("saveCaptureButton"),
    setupQr: byId("setupQr"),
    certificateFingerprint: byId("certificateFingerprint"),
    legacyButton: byId("legacyButton"),
    legacyDialog: byId("legacyDialog"),
    runSimulationButton: byId("runSimulationButton"),
    snapshotInput: byId("snapshotInput"),
    legacyRunStatus: byId("legacyRunStatus"),
  };

  const viewPanels = new Map(
    Array.from(document.querySelectorAll("[data-view]")).map((panel) => [panel.dataset.view, panel]),
  );
  const pipeline = new PipelineStateMachine("LIVE");
  let viewMode = "auto";
  let primaryView = "live";
  let workspaceMode = "phone";
  let latestCameraState = null;
  let cameraShouldStream = false;
  let liveStreamStarted = false;
  let latestPairingRevision = -1;
  let latestCaptureRevision = -1;
  let cameraStateTimer = 0;
  let noticeTimer = 0;
  let targetPerceptionState = null;
  let analysisFrozen = false;
  let targetAnalysisRunning = false;
  let targetAnalysisRequest = 0;
  let historicalObjectUrls = [];

  function showNotice(message, type = "success") {
    window.clearTimeout(noticeTimer);
    els.notice.textContent = message;
    els.notice.className = `workspace-notice is-${type}`;
    els.notice.hidden = false;
    noticeTimer = window.setTimeout(() => { els.notice.hidden = true; }, 4400);
  }

  function openDialog(dialog) {
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }

  function closeDialog(dialog) {
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  }

  async function apiPost(path, body = {}) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    let document = null;
    try { document = await response.json(); } catch { /* handled below */ }
    if (!response.ok || document?.status === "error") {
      throw new Error(document?.message || `本地服务返回 HTTP ${response.status}`);
    }
    return document;
  }

  function formatResolution(resolution) {
    return resolution ? `${resolution.width} × ${resolution.height}` : "—";
  }

  function formatMetric(value, suffix, digits = 1) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? `${number.toFixed(digits)}${suffix}` : "—";
  }

  function cameraIsLive() {
    return latestCameraState?.connection?.status === "LIVE";
  }

  function updateActionButtons() {
    const phoneLive = workspaceMode === "phone"
      && els.sourceSelect.value === "phone"
      && cameraIsLive();
    const mayAnalyze = phoneLive && pipeline.state === "LIVE" && !targetAnalysisRunning;
    const mayStart = phoneLive && canStartGrasp(pipeline.state, targetPerceptionState);
    els.analyzeTargetsButton.disabled = !mayAnalyze;
    els.startGraspButton.disabled = !mayStart;
    els.startGraspLabel.textContent = mayStart ? "开始抓取" : "请选择目标";
    els.startGraspHint.textContent = mayStart ? "Start Grasp" : "Select Target";
  }

  function renderTargetHitboxes(state) {
    els.targetOverlay.replaceChildren();
    const frame = state?.frame;
    const candidates = Array.isArray(state?.candidates) ? state.candidates : [];
    if (!frame || !candidates.length) {
      els.targetOverlay.hidden = true;
      return;
    }
    els.targetOverlay.setAttribute("viewBox", `0 0 ${frame.width} ${frame.height}`);
    candidates.forEach((candidate, index) => {
      const [x1, y1, x2, y2] = candidate.bbox_xyxy;
      const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
      const box = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      group.classList.add("target-candidate");
      if (candidate.id === state.selected_target_id) group.classList.add("is-selected");
      else if (state.selected_target_id) group.classList.add("is-dimmed");
      group.setAttribute("role", "button");
      group.setAttribute("tabindex", "0");
      group.setAttribute("aria-label", `选择候选 ${index + 1} ${candidate.class_name}`);
      box.setAttribute("x", String(x1));
      box.setAttribute("y", String(y1));
      box.setAttribute("width", String(x2 - x1));
      box.setAttribute("height", String(y2 - y1));
      box.setAttribute("rx", "4");
      group.append(box);
      const select = (event) => {
        event.stopPropagation();
        selectTarget(candidate.id);
      };
      group.addEventListener("click", select);
      group.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") select(event);
      });
      els.targetOverlay.append(group);
    });
    els.targetOverlay.hidden = false;
  }

  function renderTargetPerception(state) {
    if (!state || state.schema_version !== TARGET_PERCEPTION_SCHEMA_VERSION) {
      throw new Error("Target Perception API 版本不匹配");
    }
    targetPerceptionState = state;
    const candidates = Array.isArray(state.candidates) ? state.candidates : [];
    const selected = state.selected_target;
    const frame = state.frame;
    renderTargetHitboxes(state);
    els.analysisControls.hidden = !analysisFrozen;
    els.analysisStatus.textContent = state.message || "等待目标分析 WAITING";
    if (selected) {
      els.targetStatus.textContent = "TARGET LOCKED";
      els.targetValue.textContent = selected.id;
      els.targetClassValue.textContent = selected.class_name || "未知目标 Unknown Object";
      els.targetConfidenceValue.textContent = Number.isFinite(Number(selected.confidence))
        ? `${(Number(selected.confidence) * 100).toFixed(1)}%`
        : "NOT AVAILABLE";
      els.targetLockValue.textContent = "已锁定 LOCKED";
      els.targetDetail.textContent = `源帧 Frame ${selected.source_frame_id} · 手动选择 Manual Selection`;
    } else {
      els.targetStatus.textContent = state.status === "NO_CANDIDATES" ? "NO CANDIDATES" : candidates.length ? "SELECTABLE" : "WAITING";
      els.targetValue.textContent = candidates.length ? `${candidates.length} 个候选 Candidates` : "等待选择 WAITING";
      els.targetClassValue.textContent = "NOT AVAILABLE";
      els.targetConfidenceValue.textContent = "NOT AVAILABLE";
      els.targetLockValue.textContent = candidates.length ? "等待选择 SELECTABLE" : "WAITING";
      els.targetDetail.textContent = candidates.length
        ? "点击真实帧中的任一候选区域以锁定目标。"
        : state.status === "NO_CANDIDATES"
          ? "当前冻结帧未发现有效目标候选；可返回实时画面后重新分析。"
          : "连接手机后分析真实 RGB 帧，再手动选择目标。";
    }
    if (frame && analysisFrozen) {
      els.liveResolution.textContent = `${frame.width} × ${frame.height}`;
      els.liveSourceLabel.textContent = `手机 Phone · 冻结帧 Frame ${frame.id}`;
    }
    updateActionButtons();
  }

  function setPrimaryView(view) {
    if (!viewPanels.has(view)) return;
    primaryView = view;
    const auxiliaryViews = [...viewPanels.keys()].filter((key) => key !== view);
    viewPanels.forEach((panel, key) => {
      const primary = key === view;
      panel.classList.toggle("is-primary", primary);
      panel.dataset.slot = primary ? "primary" : String(auxiliaryViews.indexOf(key) + 1);
      panel.setAttribute("aria-current", primary ? "true" : "false");
    });
    els.statusPrimaryView.textContent = VIEW_LABELS[view];
  }

  function setViewMode(mode, pinnedView = primaryView) {
    viewMode = mode === "manual" ? "manual" : "auto";
    els.viewModeSelect.value = viewMode;
    els.statusViewMode.textContent = viewMode === "auto" ? "Auto Follow" : "Manual Pin";
    setPrimaryView(viewMode === "auto" ? pipeline.primaryView() : pinnedView);
  }

  function renderPipeline(event = null) {
    const state = event?.state || pipeline.state;
    els.pipelineBadge.textContent = state;
    els.pipelineMessage.textContent = PIPELINE_MESSAGES[state];
    els.systemStatus.textContent = state === "LIVE" ? "READY" : state;
    [els.spatialState, els.graspState, els.simulationState].forEach((element) => element.classList.remove("is-active"));
    if (state === "SPATIAL_ANALYSIS") els.spatialState.classList.add("is-active");
    if (["GRASP_PLANNING", "SCENE_SYNC"].includes(state)) els.graspState.classList.add("is-active");
    if (["SIMULATION", "VERIFIED"].includes(state)) els.simulationState.classList.add("is-active");
    if (viewMode === "auto") setPrimaryView(pipeline.primaryView());
    updateActionButtons();
  }

  pipeline.subscribe(renderPipeline);

  function pinView(view) {
    setViewMode("manual", view);
    showNotice(`已固定主视图：${VIEW_LABELS[view]}。选择 Auto Follow 可恢复阶段跟随。`);
  }

  function clearHistoricalUrls() {
    historicalObjectUrls.forEach((url) => URL.revokeObjectURL(url));
    historicalObjectUrls = [];
  }

  function clearMediaElement(image, empty) {
    image.hidden = true;
    image.removeAttribute("src");
    empty.hidden = false;
  }

  function clearWorkspaceOutputs() {
    clearHistoricalUrls();
    clearMediaElement(els.spatialSnapshot, els.spatialEmpty);
    clearMediaElement(els.graspMedia, els.graspEmpty);
    clearMediaElement(els.simulationMedia, els.simulationEmpty);
    els.spatialPendingOverlay.hidden = true;
    els.spatialState.textContent = "WAITING";
    els.graspState.textContent = "WAITING";
    els.simulationState.textContent = "WAITING";
    els.spatialFooter.textContent = "NOT AVAILABLE";
    els.graspFooter.textContent = "NOT AVAILABLE";
    els.simulationFooter.textContent = "NOT AVAILABLE";
    [els.spatialState, els.graspState, els.simulationState].forEach((element) => element.classList.remove("has-data"));
    els.targetStatus.textContent = "WAITING";
    els.targetValue.textContent = "等待选择 WAITING";
    els.targetClassValue.textContent = "NOT AVAILABLE";
    els.targetConfidenceValue.textContent = "NOT AVAILABLE";
    els.targetLockValue.textContent = "WAITING";
    els.targetDetail.textContent = "连接手机后分析真实 RGB 帧，再手动选择目标。";
    els.spatialInspectorStatus.textContent = "WAITING";
    els.spatialValue.textContent = "等待计算 WAITING";
    els.spatialDetail.textContent = "Depth、XYZ 与 Point Cloud 均不可用。";
    els.graspInspectorStatus.textContent = "WAITING";
    els.graspValue.textContent = "等待规划 WAITING";
    els.graspDetail.textContent = "角度、宽度、评分与碰撞结果均不可用。";
    els.statusSnapshot.textContent = "WAITING";
    els.legacyRunStatus.textContent = "尚未载入 NOT LOADED";
    targetPerceptionState = null;
    analysisFrozen = false;
    targetAnalysisRunning = false;
    targetAnalysisRequest += 1;
    els.targetOverlay.replaceChildren();
    els.targetOverlay.hidden = true;
    els.analysisControls.hidden = true;
    els.analysisStatus.textContent = "等待目标分析 WAITING";
    updateActionButtons();
  }

  function startLiveView() {
    if (analysisFrozen || liveStreamStarted || workspaceMode !== "phone" || els.sourceSelect.value !== "phone") return;
    liveStreamStarted = true;
    els.liveMedia.src = `/api/camera/live.mjpeg?opened=${Date.now()}`;
    els.liveMedia.onload = () => {
      if (workspaceMode !== "phone" || analysisFrozen) return;
      els.liveMedia.hidden = false;
      els.liveEmpty.hidden = true;
    };
    els.liveMedia.onerror = () => {
      liveStreamStarted = false;
      els.liveMedia.hidden = true;
      els.liveEmpty.hidden = false;
      window.setTimeout(() => {
        if (workspaceMode === "phone" && cameraShouldStream && !analysisFrozen) startLiveView();
      }, 1200);
    };
  }

  function stopLiveView() {
    liveStreamStarted = false;
    els.liveMedia.onload = null;
    els.liveMedia.onerror = null;
    els.liveMedia.removeAttribute("src");
    els.liveMedia.hidden = true;
    els.liveEmpty.hidden = false;
  }

  function renderCameraState(state) {
    latestCameraState = state;
    const connection = state.connection || {};
    const pairing = state.pairing || {};
    const device = state.device || {};
    const service = state.service || {};
    const capture = state.capture || {};
    const live = connection.status === "LIVE";
    const paired = device.paired === true;
    const resolution = formatResolution(connection.resolution);
    const fps = formatMetric(connection.fps, " FPS");
    const latency = formatMetric(connection.latency_ms, " ms");
    cameraShouldStream = live;

    els.cameraConnectionState.textContent = connection.status || "WAITING";
    els.cameraDevice.textContent = device.name || "Phone Camera";
    els.cameraConnection.textContent = live ? "LAN Connected" : paired ? "Device paired" : "Waiting";
    els.cameraMode.textContent = connection.mode || "IDLE";
    els.cameraSideResolution.textContent = resolution;
    els.cameraSideFps.textContent = fps;
    els.cameraSideLatency.textContent = latency;
    els.pairingState.textContent = pairing.status || "WAITING";
    els.cameraLanAddress.textContent = service.lan_address || "—";
    els.pairedDevice.textContent = paired ? (device.name || "Phone Camera") : "Not paired";
    els.certificateFingerprint.textContent = service.certificate_fingerprint_sha256 || "—";

    if (!paired && pairing.revision !== latestPairingRevision) {
      latestPairingRevision = pairing.revision;
      els.pairingQr.src = `/api/camera/pairing-qr.png?revision=${pairing.revision}`;
    }

    if (workspaceMode === "phone" && els.sourceSelect.value === "phone") {
      els.liveState.textContent = live ? "LIVE" : paired ? "PAIRED" : "DISCONNECTED";
      els.liveState.classList.toggle("is-live", live);
      els.liveSourceLabel.textContent = live ? "手机 Phone · WebRTC LAN Live" : "手机 Phone · 等待连接";
      els.liveResolution.textContent = resolution;
      els.liveConnection.textContent = live ? "Live" : connection.status || "Disconnected";
      els.statusConnection.textContent = live ? "Live" : paired ? "Paired" : "Disconnected";
      updateActionButtons();
      if (live && !analysisFrozen) startLiveView();
      else if (!live && liveStreamStarted) stopLiveView();
    }

    if (capture.available) {
      const captureResolution = formatResolution(capture.resolution);
      els.captureResolution.textContent = captureResolution;
      els.captureStatus.textContent = capture.saved_path
        ? `高清原图已保存：${capture.saved_path}`
        : `已从手机收到高清原图 ${captureResolution}；当前仅保存在内存。`;
      els.saveCaptureButton.disabled = false;
      if (capture.revision !== latestCaptureRevision) {
        latestCaptureRevision = capture.revision;
        els.captureImage.src = `/api/camera/capture?revision=${capture.revision}`;
        els.captureImage.hidden = false;
        els.captureEmpty.hidden = true;
      }
    }
  }

  async function pollCameraState() {
    try {
      const response = await fetch(`/api/camera/state?t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const state = await response.json();
      if (state.schema_version !== CAMERA_SCHEMA_VERSION) throw new Error("Camera API 版本不匹配");
      renderCameraState(state);
    } catch (error) {
      els.cameraConnectionState.textContent = "OFFLINE";
      els.cameraConnection.textContent = `Camera Service 未连接：${error.message}`;
      if (workspaceMode === "phone" && els.sourceSelect.value === "phone") {
        els.liveState.textContent = "OFFLINE";
        els.liveConnection.textContent = "Offline";
        els.statusConnection.textContent = "Offline";
        els.analyzeTargetsButton.disabled = true;
        els.startGraspButton.disabled = true;
      }
    }
  }

  async function selectSource(source) {
    workspaceMode = "phone";
    stopLiveView();
    if (pipeline.state !== "LIVE") pipeline.reset({ reason: "source-changed" });
    try { await apiPost("/api/target-perception/reset"); } catch { /* source switch still clears local state */ }
    clearWorkspaceOutputs();
    if (source === "phone") {
      els.liveSourceLabel.textContent = "手机 Phone · 等待连接";
      if (latestCameraState) renderCameraState(latestCameraState);
      showNotice("已选择手机 Phone；连接能力沿用现有 WebRTC LAN 链路。");
      return;
    }
    stopLiveView();
    els.liveState.textContent = "PENDING";
    els.liveState.classList.remove("is-live", "has-data");
    els.liveSourceLabel.textContent = `${SOURCE_LABELS[source]} · MODULE PENDING`;
    els.liveResolution.textContent = "—";
    els.liveConnection.textContent = "Not Available";
    els.statusConnection.textContent = "Module Pending";
    updateActionButtons();
    showNotice(`${SOURCE_LABELS[source]} 接口已预留，本轮未接入。`, "error");
  }

  function showFrozenTargetFrame(state) {
    analysisFrozen = true;
    stopLiveView();
    els.liveMedia.onload = () => {
      els.liveMedia.hidden = false;
      els.liveEmpty.hidden = true;
    };
    els.liveMedia.onerror = () => showNotice("无法显示目标分析叠加图。", "error");
    els.liveMedia.src = `/api/target-perception/overlay.jpg?revision=${state.revision}`;
    els.liveState.textContent = state.status === "TARGET_LOCKED" ? "TARGET LOCKED" : "FRAME FROZEN";
    els.liveState.classList.add("is-live");
    renderTargetPerception(state);
  }

  async function analyzeTargets() {
    if (targetAnalysisRunning || pipeline.state !== "LIVE" || !cameraIsLive()) return;
    const requestRevision = ++targetAnalysisRequest;
    targetAnalysisRunning = true;
    els.analysisControls.hidden = false;
    els.analysisStatus.textContent = "正在冻结真实帧并分析目标 ANALYZING";
    els.analyzeTargetsButton.querySelector("span").textContent = "分析中…";
    els.analyzeTargetsButton.querySelector("small").textContent = "Analyzing";
    updateActionButtons();
    try {
      const state = await apiPost("/api/target-perception/analyze");
      if (requestRevision !== targetAnalysisRequest) return;
      showFrozenTargetFrame(state);
      showNotice(state.status === "NO_CANDIDATES"
        ? "当前真实帧未发现有效目标候选；未生成任何伪造目标。"
        : `已冻结真实 RGB 帧，发现 ${state.candidates.length} 个可选目标。`,
      state.status === "NO_CANDIDATES" ? "error" : "success");
    } catch (error) {
      if (requestRevision !== targetAnalysisRequest) return;
      analysisFrozen = false;
      els.analysisControls.hidden = true;
      if (cameraShouldStream) startLiveView();
      showNotice(`目标分析失败：${error.message}`, "error");
    } finally {
      targetAnalysisRunning = false;
      els.analyzeTargetsButton.querySelector("span").textContent = analysisFrozen ? "再次分析" : "分析目标";
      els.analyzeTargetsButton.querySelector("small").textContent = analysisFrozen ? "Analyze Again" : "Analyze Targets";
      updateActionButtons();
    }
  }

  async function selectTarget(targetId) {
    const frameId = targetPerceptionState?.frame?.id;
    const requestRevision = targetAnalysisRequest;
    if (!Number.isInteger(frameId) || !targetId || !["LIVE", "TARGET_SELECTED"].includes(pipeline.state)) return;
    try {
      const state = await apiPost("/api/target-perception/select", {
        target_id: targetId,
        source_frame_id: frameId,
      });
      if (requestRevision !== targetAnalysisRequest) return;
      showFrozenTargetFrame(state);
      if (pipeline.state === "LIVE") {
        pipeline.transition("TARGET_SELECTED", {
          targetId: state.selected_target_id,
          sourceFrameId: state.frame.id,
          sourceTimestampS: state.frame.timestamp_s,
        });
      }
      updateActionButtons();
      showNotice(`目标已锁定：${state.selected_target.class_name} · ${state.selected_target_id}`);
    } catch (error) {
      showNotice(`无法选择目标：${error.message}`, "error");
    }
  }

  async function resumeLive() {
    try {
      await apiPost("/api/target-perception/reset");
    } catch (error) {
      showNotice(`目标状态重置失败：${error.message}`, "error");
      return;
    }
    if (pipeline.state !== "LIVE") pipeline.reset({ reason: "resume-live" });
    clearWorkspaceOutputs();
    if (latestCameraState) renderCameraState(latestCameraState);
    showNotice("已返回实时画面 Live RGB；可重新分析目标。");
  }

  async function startGrasp() {
    if (!canStartGrasp(pipeline.state, targetPerceptionState)) return;
    const state = targetPerceptionState;
    const frame = state.frame;
    const target = state.selected_target;
    els.startGraspButton.disabled = true;
    try {
      els.spatialSnapshot.src = `/api/target-perception/scene-snapshot.jpg?revision=${state.revision}`;
      els.spatialSnapshot.hidden = false;
      els.spatialEmpty.hidden = true;
      els.spatialPendingOverlay.hidden = false;
      els.spatialState.textContent = "WAITING";
      els.spatialFooter.textContent = `FRAME ${frame.id} · ${target.id}`;
      els.statusSnapshot.textContent = `${frame.width} × ${frame.height} · Frame ${frame.id}`;
      els.spatialInspectorStatus.textContent = "WAITING";
      els.spatialValue.textContent = "等待计算 WAITING";
      els.spatialDetail.textContent = "已接收与锁定目标同帧的真实 RGB 场景快照；Depth、XYZ 与 Point Cloud 仍不可用。";
      pipeline.transition("SCENE_CAPTURED", {
        source: "phone-live-rgb",
        targetId: target.id,
        sourceFrameId: frame.id,
        sourceTimestampS: frame.timestamp_s,
      });
      pipeline.transition("SPATIAL_ANALYSIS", { module: "pending", targetId: target.id, sourceFrameId: frame.id });
      updateActionButtons();
      showNotice("真实目标与场景快照关联完成；空间分析模块未接入，流程停留在 WAITING。", "success");
    } catch (error) {
      updateActionButtons();
      showNotice(`无法开始抓取：${error.message}`, "error");
    }
  }

  async function resetPipeline() {
    workspaceMode = "phone";
    try { await apiPost("/api/target-perception/reset"); } catch { /* local reset remains available */ }
    clearWorkspaceOutputs();
    if (pipeline.state !== "LIVE") pipeline.reset({ reason: "user-reset" });
    setViewMode("auto");
    if (els.sourceSelect.value === "phone" && latestCameraState) renderCameraState(latestCameraState);
    else selectSource(els.sourceSelect.value);
    showNotice("流程已重置为 LIVE，未生成任何推断数据。");
  }

  function safeRelativePath(value) {
    const path = String(value || "").replace(/\\/g, "/").replace(/^\.\//, "");
    if (!path || path.startsWith("/") || path.split("/").includes("..")) {
      throw new Error(`媒体路径不安全：${String(value)}`);
    }
    return path;
  }

  function mediaSource(media, resolver) {
    if (!media || typeof media.path !== "string") return null;
    if (media.kind === "video") throw new Error("当前 Workspace 仅支持历史运行图片产物");
    return { src: resolver(safeRelativePath(media.path)), label: media.label || "真实运行产物" };
  }

  function setHistoricalImage(image, empty, source) {
    if (!source) {
      clearMediaElement(image, empty);
      return false;
    }
    image.src = source.src;
    image.hidden = false;
    empty.hidden = true;
    return true;
  }

  function formatVectorMm(vector) {
    if (!Array.isArray(vector) || vector.length !== 3) return "NOT AVAILABLE";
    return `X ${(vector[0] * 1000).toFixed(1)} · Y ${(vector[1] * 1000).toFixed(1)} · Z ${(vector[2] * 1000).toFixed(1)} mm`;
  }

  function renderHistoricalRun(raw, resolver) {
    if (!raw || raw.schema_version !== RUN_SCHEMA_VERSION) throw new Error("运行目录格式不受支持");
    const media = raw.media || {};
    const sources = {
      live: mediaSource(media.rgb, resolver),
      spatial: mediaSource(media.depth, resolver),
      grasp: mediaSource(media.grasp_overlay, resolver),
      simulation: mediaSource(media.mujoco, resolver),
    };
    workspaceMode = "legacy";
    analysisFrozen = false;
    targetPerceptionState = null;
    els.targetOverlay.replaceChildren();
    els.targetOverlay.hidden = true;
    els.analysisControls.hidden = true;
    stopLiveView();
    pipeline.reset({ reason: "legacy-run-loaded" });
    pipeline.transition("TARGET_SELECTED", { source: "public-run-artifact" });
    pipeline.transition("SCENE_CAPTURED", { source: "public-run-artifact" });
    pipeline.transition("SPATIAL_ANALYSIS", { source: "public-run-artifact" });
    pipeline.transition("GRASP_PLANNING", { source: "public-run-artifact" });
    pipeline.transition("SCENE_SYNC", { source: "public-run-artifact" });
    pipeline.transition("SIMULATION", { source: "public-run-artifact" });
    if (raw.execution) pipeline.transition("VERIFIED", { source: "public-run-artifact" });

    const hasLive = setHistoricalImage(els.liveMedia, els.liveEmpty, sources.live);
    const hasSpatial = setHistoricalImage(els.spatialSnapshot, els.spatialEmpty, sources.spatial);
    const hasGrasp = setHistoricalImage(els.graspMedia, els.graspEmpty, sources.grasp);
    const hasSimulation = setHistoricalImage(els.simulationMedia, els.simulationEmpty, sources.simulation);
    els.spatialPendingOverlay.hidden = true;
    els.liveState.textContent = hasLive ? "RUN DATA" : "NO DATA";
    els.liveState.classList.toggle("has-data", hasLive);
    els.liveSourceLabel.textContent = sources.live?.label || "历史运行 · NOT AVAILABLE";
    els.liveResolution.textContent = raw.target?.image_size_px
      ? formatResolution(raw.target.image_size_px)
      : "—";
    els.liveConnection.textContent = "Offline Artifact";
    els.statusConnection.textContent = "Offline Artifact";
    els.spatialState.textContent = hasSpatial ? "RUN DATA" : "NOT AVAILABLE";
    els.spatialState.classList.toggle("has-data", hasSpatial);
    els.spatialFooter.textContent = sources.spatial?.label || "NOT AVAILABLE";
    els.graspState.textContent = hasGrasp ? "RUN DATA" : "NOT AVAILABLE";
    els.graspState.classList.toggle("has-data", hasGrasp);
    els.graspFooter.textContent = sources.grasp?.label || "NOT AVAILABLE";
    els.simulationState.textContent = hasSimulation ? "RUN DATA" : "NOT AVAILABLE";
    els.simulationState.classList.toggle("has-data", hasSimulation);
    els.simulationFooter.textContent = sources.simulation?.label || "NOT AVAILABLE";
    els.startGraspButton.disabled = true;
    els.statusSnapshot.textContent = "Offline Run";

    if (raw.target) {
      els.targetStatus.textContent = "AVAILABLE";
      els.targetValue.textContent = raw.target.class_name || "真实运行目标";
      els.targetClassValue.textContent = raw.target.class_name || "NOT AVAILABLE";
      const confidence = Number(raw.target.confidence);
      els.targetConfidenceValue.textContent = Number.isFinite(confidence)
        ? `${(confidence * 100).toFixed(1)}%`
        : "NOT AVAILABLE";
      els.targetLockValue.textContent = "离线产物 OFFLINE";
      els.targetDetail.textContent = Number.isFinite(confidence)
        ? `离线运行公开输出 · 置信度 ${(confidence * 100).toFixed(1)}%`
        : "离线运行公开目标输出。";
      els.spatialInspectorStatus.textContent = "AVAILABLE";
      els.spatialValue.textContent = formatVectorMm(raw.target.centroid_world_m);
      els.spatialDetail.textContent = "来自导入的公开离线运行产物；不是 Phone RGB 实时计算结果。";
    }

    const selected = Array.isArray(raw.candidates)
      ? raw.candidates.find((candidate) => candidate.candidate_id === raw.selected_candidate_id) || raw.candidates[0]
      : null;
    if (selected) {
      const width = Number(selected.gripper_width_m);
      const score = Number(selected.score);
      els.graspInspectorStatus.textContent = "AVAILABLE";
      els.graspValue.textContent = `候选 ${selected.candidate_id || "—"}`;
      els.graspDetail.textContent = [
        Number.isFinite(width) ? `宽度 ${(width * 1000).toFixed(1)} mm` : "宽度 NOT AVAILABLE",
        Number.isFinite(score) ? `评分 ${score.toFixed(3)}` : "评分 NOT AVAILABLE",
      ].join(" · ");
    }
    els.legacyRunStatus.textContent = raw.run_id || "已载入 LOADED";
    closeDialog(els.legacyDialog);
    showNotice(`已载入真实离线运行产物：${raw.run_id}`);
  }

  async function loadPublishedRun() {
    const manifestUrl = new URL(PUBLISHED_MANIFEST_URL, window.location.href);
    manifestUrl.searchParams.set("t", String(Date.now()));
    const manifestResponse = await fetch(manifestUrl, { cache: "no-store" });
    if (!manifestResponse.ok) throw new Error(`运行清单返回 HTTP ${manifestResponse.status}`);
    const manifest = await manifestResponse.json();
    if (manifest.schema_version !== PUBLISHED_SCHEMA_VERSION) throw new Error("运行清单版本不受支持");
    const runPath = safeRelativePath(manifest.run_json);
    const runUrl = new URL(runPath, new URL("../../runtime/", window.location.href));
    runUrl.searchParams.set("t", String(Date.now()));
    const runResponse = await fetch(runUrl, { cache: "no-store" });
    if (!runResponse.ok) throw new Error(`run.json 返回 HTTP ${runResponse.status}`);
    const raw = await runResponse.json();
    renderHistoricalRun(raw, (path) => new URL(path, runUrl).href);
  }

  async function importRunDirectory(fileList) {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    const runFiles = files.filter((file) => file.name.toLowerCase() === "run.json");
    if (runFiles.length !== 1) throw new Error(`目录中需要且只能有一个 run.json，当前找到 ${runFiles.length} 个`);
    const runFile = runFiles[0];
    const runRelativePath = safeRelativePath(runFile.webkitRelativePath || runFile.name);
    const runDirectory = runRelativePath.includes("/") ? runRelativePath.slice(0, runRelativePath.lastIndexOf("/")) : "";
    const filesByPath = new Map(files.map((file) => [safeRelativePath(file.webkitRelativePath || file.name), file]));
    const raw = JSON.parse(await runFile.text());
    clearHistoricalUrls();
    renderHistoricalRun(raw, (path) => {
      const fullPath = runDirectory ? `${runDirectory}/${path}` : path;
      const mediaFile = filesByPath.get(fullPath);
      if (!mediaFile) throw new Error(`缺少媒体文件：${path}`);
      const url = URL.createObjectURL(mediaFile);
      historicalObjectUrls.push(url);
      return url;
    });
  }

  document.querySelectorAll("[data-pin-view]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      pinView(button.dataset.pinView);
    });
  });
  viewPanels.forEach((panel, view) => {
    panel.addEventListener("click", (event) => {
      if (view === primaryView || event.target.closest("button, a, select, input, label")) return;
      pinView(view);
    });
  });
  document.querySelectorAll("[data-open-camera-setup]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openDialog(els.cameraSetupDialog);
    });
  });

  els.sourceSelect.addEventListener("change", () => selectSource(els.sourceSelect.value));
  els.conditionSelect.addEventListener("change", () => {
    const pending = els.conditionSelect.value !== "normal";
    showNotice(pending ? "测试条件入口已预留；本轮不会对真实画面施加退化。" : "已选择正常条件 Normal。", pending ? "error" : "success");
  });
  els.robotSelect.addEventListener("change", () => {
    const pending = els.robotSelect.value !== "panda";
    showNotice(pending ? "UR5e 接口已预留；本轮不执行多机器人仿真。" : "已选择 Franka Panda。", pending ? "error" : "success");
  });
  els.viewModeSelect.addEventListener("change", () => setViewMode(els.viewModeSelect.value));
  els.analyzeTargetsButton.addEventListener("click", analyzeTargets);
  els.startGraspButton.addEventListener("click", startGrasp);
  els.resumeLiveButton.addEventListener("click", resumeLive);
  els.resetPipelineButton.addEventListener("click", resetPipeline);
  els.cameraSetupButton.addEventListener("click", () => openDialog(els.cameraSetupDialog));
  document.querySelector("[data-close-camera-setup]").addEventListener("click", () => closeDialog(els.cameraSetupDialog));
  els.cameraSetupDialog.addEventListener("click", (event) => {
    if (event.target === els.cameraSetupDialog) closeDialog(els.cameraSetupDialog);
  });
  els.legacyButton.addEventListener("click", () => openDialog(els.legacyDialog));
  document.querySelector("[data-close-legacy]").addEventListener("click", () => closeDialog(els.legacyDialog));
  els.legacyDialog.addEventListener("click", (event) => {
    if (event.target === els.legacyDialog) closeDialog(els.legacyDialog);
  });
  els.refreshPairingButton.addEventListener("click", async () => {
    els.refreshPairingButton.disabled = true;
    try {
      await apiPost("/api/camera/pairing/refresh");
      const nonce = Date.now();
      els.pairingQr.src = `/api/camera/pairing-qr.png?t=${nonce}`;
      els.setupQr.src = `/api/camera/setup-qr.png?t=${nonce}`;
      latestPairingRevision = -1;
      if (workspaceMode === "phone") stopLiveView();
      await pollCameraState();
      showNotice("已生成新的五分钟一次性配对二维码。");
    } catch (error) {
      showNotice(`无法刷新配对：${error.message}`, "error");
    } finally {
      els.refreshPairingButton.disabled = false;
    }
  });
  els.saveCaptureButton.addEventListener("click", async () => {
    els.saveCaptureButton.disabled = true;
    try {
      const result = await apiPost("/api/camera/capture/save");
      showNotice(`高清原图已保存：${result.path}`);
      await pollCameraState();
    } catch (error) {
      showNotice(`保存失败：${error.message}`, "error");
    } finally {
      els.saveCaptureButton.disabled = false;
    }
  });
  els.runSimulationButton.addEventListener("click", async () => {
    els.runSimulationButton.disabled = true;
    els.runSimulationButton.textContent = "离线验证运行中…";
    els.legacyRunStatus.textContent = "RUNNING";
    try {
      await apiPost("/api/simulation/run");
      await loadPublishedRun();
    } catch (error) {
      els.legacyRunStatus.textContent = "FAILED";
      showNotice(`离线验证失败：${error.message}`, "error");
    } finally {
      els.runSimulationButton.disabled = false;
      els.runSimulationButton.textContent = "运行离线验证 Run Offline";
    }
  });
  els.snapshotInput.addEventListener("change", async () => {
    try {
      await importRunDirectory(els.snapshotInput.files);
    } catch (error) {
      showNotice(`无法导入运行目录：${error.message}`, "error");
    } finally {
      els.snapshotInput.value = "";
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && viewMode === "manual" && !els.cameraSetupDialog.open && !els.legacyDialog.open) {
      setViewMode("auto");
    }
  });
  window.addEventListener("beforeunload", () => {
    window.clearInterval(cameraStateTimer);
    clearHistoricalUrls();
  });

  renderPipeline();
  setPrimaryView("live");
  pollCameraState();
  cameraStateTimer = window.setInterval(pollCameraState, 1000);
})();
