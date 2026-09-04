(() => {
  "use strict";

  const CAMERA_SCHEMA_VERSION = "vision2grasp.camera/v1";
  const TARGET_PERCEPTION_SCHEMA_VERSION = "gongshu.target-perception/v1";
  const SPATIAL_PERCEPTION_SCHEMA_VERSION = "gongshu.spatial-perception/v2";
  const GRASP_PLANNING_SCHEMA_VERSION = "gongshu.grasp-planning-job/v2";
  const MUJOCO_VALIDATION_SCHEMA_VERSION = "gongshu.mujoco-validation/v4";
  const RUN_SCHEMA_VERSION = "vision2grasp.run/v1";
  const PUBLISHED_SCHEMA_VERSION = "vision2grasp.launcher/v1";
  const PUBLISHED_MANIFEST_URL = "../../runtime/latest.json";
  const {
    PipelineStateMachine,
    canStartGrasp,
    hasSpatialObservationAssociation,
    hasGraspPlanAssociation,
    hasGraspOutcomeAssociation,
  } = window.GongshuPipeline;
  const {
    clientPointToSource,
    canSelectFrozenTarget,
  } = window.GongshuTargetSelection;

  const PIPELINE_MESSAGES = Object.freeze({
    LIVE: "实时视觉已就绪，等待真实输入",
    TARGET_SELECTED: "已接收真实目标选择",
    SCENE_CAPTURED: "已获取真实 RGB 场景快照",
    SPATIAL_ANALYSIS: "正在从冻结场景快照计算空间结构",
    SPATIAL_READY: "空间感知完成，三维空间链条已就绪",
    GRASP_PLANNING: "真实空间结果已进入抓取规划",
    SCENE_SYNC: "正在映射至规范化仿真场景 · SIMULATION ONLY",
    SIMULATION: "真实连续 MuJoCo Physics 仿真验证进行中",
    VERIFIED: "Simulation Validation 已完成",
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

  const CONDITION_LABELS = Object.freeze({
    NORMAL: "正常条件 Normal",
    BLUR: "模糊条件 Blur",
    LOW_LIGHT: "低光条件 Low-Light",
    LOW_LIGHT_BLUR: "低光与模糊 Low-Light + Blur",
  });
  const STRESS_LEVEL_LABELS = Object.freeze({
    MILD: "轻度 Mild",
    MODERATE: "中度 Moderate",
    SEVERE: "严重 Severe",
  });
  const STRESS_STRATEGY_LABELS = Object.freeze({
    STRESS_ONLY: "仅压力测试 Stress Only",
    STRESS_PLUS_RECOVERY: "压力测试与恢复 Stress + Recovery",
  });
  const ENHANCEMENT_LABELS = Object.freeze({
    NOT_REQUIRED: "无需增强 Not Required",
    ASSESSMENT_ONLY: "仅评估 Assessment Only",
    APPLIED: "已应用 Applied",
    REVERTED: "已回退 Reverted",
    FAILED: "处理失败 Failed",
    PENDING_NOT_IMPLEMENTED: "待实现 Pending",
  });
  const RELIABILITY_LABELS = Object.freeze({
    HIGH: "高 High",
    MEDIUM: "中 Medium",
    LOW: "低 Low",
  });
  const CONDITION_CHAIN_LABELS = Object.freeze({
    BRIGHTNESS_REDUCTION: "亮度降低 Brightness Reduction",
    CONTRAST_REDUCTION: "对比度降低 Contrast Reduction",
    SHADOW_NOISE: "暗部噪声 Shadow Noise",
    GAUSSIAN_BLUR: "高斯模糊 Gaussian Blur",
    MOTION_BLUR: "运动模糊 Motion Blur",
    EXPOSURE_RECOVERY_CLAHE: "曝光恢复 Exposure Recovery",
    MILD_DENOISE_BILATERAL: "轻量降噪 Mild Denoise",
    UNSHARP_MASK: "反锐化增强 Unsharp Mask",
  });
  const CONDITION_WARNING_LABELS = Object.freeze({
    BLUR_TOO_SEVERE: "严重模糊 Blur Too Severe",
    LOW_LIGHT_TOO_SEVERE: "严重低光 Low-Light Too Severe",
    LOW_IMAGE_QUALITY: "图像质量不足 Low Image Quality",
    PERCEPTION_UNCERTAIN: "感知不确定 Perception Uncertain",
    DEPTH_UNRELIABLE: "深度可靠性不足 Depth Unreliable",
  });

  const SPATIAL_ERROR_MESSAGES = Object.freeze({
    DEPTH_UNAVAILABLE: "深度不可用 DEPTH UNAVAILABLE",
    MODEL_NOT_FOUND: "未找到深度模型 MODEL NOT FOUND",
    DOWNLOAD_FAILED: "深度模型下载失败 DOWNLOAD FAILED",
    CHECKSUM_FAILED: "深度模型校验失败 CHECKSUM FAILED",
    MODEL_LOAD_FAILED: "深度模型加载失败 MODEL LOAD FAILED",
    TARGET_MASK_EMPTY: "目标掩膜为空 TARGET MASK EMPTY",
    TOO_FEW_VALID_DEPTH_PIXELS: "有效深度像素不足 INSUFFICIENT DEPTH",
    INVALID_INTRINSICS: "相机投影参数无效 INVALID PROJECTION PARAMETERS",
    FRAME_MISMATCH: "场景快照关联不一致 FRAME MISMATCH",
    TARGET_MISMATCH: "目标实例关联不一致 TARGET MISMATCH",
    POINT_CLOUD_EMPTY: "目标点云为空 POINT CLOUD EMPTY",
    DOWNLOAD_TIMEOUT: "模型下载超时 DOWNLOAD TIMEOUT",
    CHECKSUM_TIMEOUT: "模型校验超时 CHECKSUM TIMEOUT",
    MODEL_LOAD_TIMEOUT: "模型加载超时 MODEL LOAD TIMEOUT",
    DEPTH_INFERENCE_TIMEOUT: "深度推理超时 DEPTH INFERENCE TIMEOUT",
    POINT_CLOUD_TIMEOUT: "点云生成超时 POINT CLOUD TIMEOUT",
    SPATIAL_COMPUTE_TIMEOUT: "空间计算超时 SPATIAL COMPUTE TIMEOUT",
    SPATIAL_JOB_CANCELLED: "空间任务已取消 SPATIAL JOB CANCELLED",
    SPATIAL_ANALYSIS_FAILED: "空间分析失败 SPATIAL ERROR",
  });

  const GRASP_REJECTION_MESSAGES = Object.freeze({
    LOW_GRASP_QUALITY: "抓取置信度不足",
    GRIPPER_TOO_NARROW: "预测夹爪开口小于最小宽度",
    GRIPPER_TOO_WIDE: "目标所需开口超过夹爪最大宽度",
    TARGET_EDGE: "候选过于接近目标边缘",
    INVALID_DEPTH: "候选局部深度无效",
    NO_VALID_CANDIDATE: "没有有效抓取候选",
  });

  function graspRejectionLabel(code, mode = "RESEARCH") {
    const reasons = String(code || "NO_VALID_CANDIDATE").split("+").filter(Boolean);
    if (mode !== "DEMO") return reasons.join(" + ");
    return reasons.map((reason) => GRASP_REJECTION_MESSAGES[reason] || reason).join("；");
  }

  const byId = (id) => document.getElementById(id);
  const els = {
    pipelineBadge: byId("pipelineBadge"),
    pipelineMessage: byId("pipelineMessage"),
    sourceSelect: byId("sourceSelect"),
    conditionSelect: byId("conditionSelect"),
    conditionStatus: byId("conditionStatus"),
    conditionVisualValue: byId("conditionVisualValue"),
    conditionLevelValue: byId("conditionLevelValue"),
    conditionQualityValue: byId("conditionQualityValue"),
    conditionEnhancementValue: byId("conditionEnhancementValue"),
    conditionReliabilityValue: byId("conditionReliabilityValue"),
    conditionDetail: byId("conditionDetail"),
    conditionSettingsButton: byId("conditionSettingsButton"),
    conditionDialog: byId("conditionDialog"),
    stressStrategySelect: byId("stressStrategySelect"),
    stressLevelSelect: byId("stressLevelSelect"),
    stressBlurTypeSelect: byId("stressBlurTypeSelect"),
    stressSeedInput: byId("stressSeedInput"),
    conditionRawPreview: byId("conditionRawPreview"),
    conditionPipelinePreview: byId("conditionPipelinePreview"),
    conditionCompareStatus: byId("conditionCompareStatus"),
    conditionFrameChain: byId("conditionFrameChain"),
    robotSelect: byId("robotSelect"),
    viewModeSelect: byId("viewModeSelect"),
    graspModeSelect: byId("graspModeSelect"),
    analyzeTargetsButton: byId("analyzeTargetsButton"),
    startGraspButton: byId("startGraspButton"),
    startGraspLabel: byId("startGraspLabel"),
    startGraspHint: byId("startGraspHint"),
    resetPipelineButton: byId("resetPipelineButton"),
    liveState: byId("liveState"),
    liveEmpty: byId("liveEmpty"),
    liveMedia: byId("liveMedia"),
    targetOverlay: byId("targetOverlay"),
    visionScanFx: byId("visionScanFx"),
    targetLockBanner: byId("targetLockBanner"),
    analysisControls: byId("analysisControls"),
    analysisStatus: byId("analysisStatus"),
    resumeLiveButton: byId("resumeLiveButton"),
    liveSourceLabel: byId("liveSourceLabel"),
    liveResolution: byId("liveResolution"),
    liveConnection: byId("liveConnection"),
    spatialState: byId("spatialState"),
    spatialSnapshot: byId("spatialSnapshot"),
    spatialMediaLabels: byId("spatialMediaLabels"),
    spatialEmpty: byId("spatialEmpty"),
    spatialPendingOverlay: byId("spatialPendingOverlay"),
    spatialProgressTitle: byId("spatialProgressTitle"),
    spatialProgressDetail: byId("spatialProgressDetail"),
    spatialLoadingIndicator: byId("spatialLoadingIndicator"),
    spatialElapsed: byId("spatialElapsed"),
    spatialEta: byId("spatialEta"),
    spatialDownloadProgress: byId("spatialDownloadProgress"),
    spatialDownloadBar: byId("spatialDownloadBar"),
    spatialDownloadDetail: byId("spatialDownloadDetail"),
    spatialSlowWarning: byId("spatialSlowWarning"),
    spatialModelState: byId("spatialModelState"),
    spatialTimingSummary: byId("spatialTimingSummary"),
    spatialReadyTiming: byId("spatialReadyTiming"),
    spatialModelLoadTiming: byId("spatialModelLoadTiming"),
    spatialDepthTiming: byId("spatialDepthTiming"),
    spatialPointCloudTiming: byId("spatialPointCloudTiming"),
    spatialComputeTiming: byId("spatialComputeTiming"),
    spatialTotalTiming: byId("spatialTotalTiming"),
    spatialErrorActions: byId("spatialErrorActions"),
    retrySpatialButton: byId("retrySpatialButton"),
    newSceneButton: byId("newSceneButton"),
    spatialFooter: byId("spatialFooter"),
    graspState: byId("graspState"),
    graspMedia: byId("graspMedia"),
    graspEmpty: byId("graspEmpty"),
    graspPendingOverlay: byId("graspPendingOverlay"),
    graspProgressTitle: byId("graspProgressTitle"),
    graspProgressDetail: byId("graspProgressDetail"),
    graspElapsed: byId("graspElapsed"),
    graspEta: byId("graspEta"),
    graspLayerControls: byId("graspLayerControls"),
    graspFooter: byId("graspFooter"),
    simulationState: byId("simulationState"),
    simulationMedia: byId("simulationMedia"),
    simulationEmpty: byId("simulationEmpty"),
    simulationFooter: byId("simulationFooter"),
    simulationHud: byId("simulationHud"),
    simulationHudState: byId("simulationHudState"),
    simulationCollision: byId("simulationCollision"),
    simulationLift: byId("simulationLift"),
    simulationTarget: byId("simulationTarget"),
    simulationAppearance: byId("simulationAppearance"),
    simulationTexture: byId("simulationTexture"),
    simulationAppearanceSource: byId("simulationAppearanceSource"),
    simulationResult: byId("simulationResult"),
    simulationPlanningResult: byId("simulationPlanningResult"),
    simulationPlanningReason: byId("simulationPlanningReason"),
    simulationAttemptState: byId("simulationAttemptState"),
    simulationAttemptCandidate: byId("simulationAttemptCandidate"),
    simulationPlaybackControls: byId("simulationPlaybackControls"),
    recordingAvailability: byId("recordingAvailability"),
    recordingSaveState: byId("recordingSaveState"),
    saveRecordingButton: byId("saveRecordingButton"),
    exportVideoButton: byId("exportVideoButton"),
    playPauseButton: byId("playPauseButton"),
    playbackTimeline: byId("playbackTimeline"),
    playbackCurrentTime: byId("playbackCurrentTime"),
    playbackDuration: byId("playbackDuration"),
    technicalOverlayToggle: byId("technicalOverlayToggle"),
    validationScenarioSelect: byId("validationScenarioSelect"),
    startValidationButton: byId("startValidationButton"),
    targetStatus: byId("targetStatus"),
    targetValue: byId("targetValue"),
    targetClassValue: byId("targetClassValue"),
    targetLockValue: byId("targetLockValue"),
    targetDetail: byId("targetDetail"),
    spatialInspectorStatus: byId("spatialInspectorStatus"),
    spatialDepthValue: byId("spatialDepthValue"),
    spatialValue: byId("spatialValue"),
    spatialSourceValue: byId("spatialSourceValue"),
    spatialModeValue: byId("spatialModeValue"),
    spatialProjectionValue: byId("spatialProjectionValue"),
    spatialDetail: byId("spatialDetail"),
    graspInspectorStatus: byId("graspInspectorStatus"),
    graspValue: byId("graspValue"),
    graspAngleValue: byId("graspAngleValue"),
    graspWidthValue: byId("graspWidthValue"),
    graspQualityValue: byId("graspQualityValue"),
    graspApproachValue: byId("graspApproachValue"),
    graspFrameValue: byId("graspFrameValue"),
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
    sessionHistoryList: byId("sessionHistoryList"),
    savedRunsList: byId("savedRunsList"),
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
  let spatialPerceptionState = null;
  let graspPlanningState = null;
  let validationState = null;
  let spatialAnalysisRunning = false;
  let activeSpatialJobId = null;
  let graspPlanningRunning = false;
  let activeGraspJobId = null;
  let graspLayer = "candidates";
  let validationRunning = false;
  let validationTimer = 0;
  let playbackSeekTimer = 0;
  let simulationStreamStarted = false;
  let analysisFrozen = false;
  let targetAnalysisRunning = false;
  let targetAnalysisRequest = 0;
  let liveVisionTimer = 0;
  let liveVisionRunning = false;
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

  async function apiGet(path) {
    const response = await fetch(path, { cache: "no-store" });
    let document = null;
    try { document = await response.json(); } catch { /* handled below */ }
    if (!response.ok || document?.status === "error") {
      throw new Error(document?.message || `本地服务返回 HTTP ${response.status}`);
    }
    return document;
  }

  function conditionExperimentSettings(view = "pipeline") {
    const seed = Number(els.stressSeedInput.value);
    return {
      condition: els.conditionSelect.value,
      strategy: els.stressStrategySelect.value,
      level: els.stressLevelSelect.value,
      blur_type: els.stressBlurTypeSelect.value,
      random_seed: Number.isInteger(seed) && seed >= 0 && seed <= 4294967295 ? seed : 7,
      mode: els.graspModeSelect.value,
      view,
    };
  }

  function liveConditionUrl(view = "pipeline") {
    const query = new URLSearchParams(conditionExperimentSettings(view));
    query.set("opened", String(Date.now()));
    return `/api/camera/live.mjpeg?${query.toString()}`;
  }

  function restartLiveConditionPreview() {
    if (!analysisFrozen && workspaceMode === "phone" && cameraShouldStream) {
      stopLiveView();
      startLiveView();
    }
    if (els.conditionDialog.open) renderConditionComparison();
  }

  function renderConditionComparison() {
    const frozen = analysisFrozen && targetPerceptionState?.condition_report;
    const revision = targetPerceptionState?.revision || Date.now();
    els.conditionRawPreview.hidden = false;
    els.conditionPipelinePreview.hidden = false;
    if (frozen) {
      els.conditionRawPreview.src = `/api/target-perception/condition-frame/raw.jpg?revision=${revision}`;
      els.conditionPipelinePreview.src = `/api/target-perception/condition-frame/pipeline.jpg?revision=${revision}`;
      els.conditionCompareStatus.textContent = "冻结实验帧 Frozen Experiment Frames";
    } else {
      els.conditionRawPreview.src = liveConditionUrl("raw");
      els.conditionPipelinePreview.src = liveConditionUrl("pipeline");
      els.conditionCompareStatus.textContent = "实时对比 Live Comparison";
    }
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

  function cameraConnectionLabel(status) {
    return {
      LIVE: "实时 Live",
      CONNECTED: "已连接 Connected",
      PAIRED: "已配对 Paired",
      WAITING: "等待连接 Waiting",
      DISCONNECTED: "已断开 Disconnected",
      STOPPED: "已停止 Stopped",
    }[status] || "未连接 Disconnected";
  }

  function updateActionButtons() {
    const phoneLive = workspaceMode === "phone"
      && els.sourceSelect.value === "phone"
      && cameraIsLive();
    const mayAnalyze = phoneLive && pipeline.state === "LIVE" && !targetAnalysisRunning;
    const mayStart = workspaceMode === "phone"
      && els.sourceSelect.value === "phone"
      && canStartGrasp(pipeline.state, targetPerceptionState);
    els.analyzeTargetsButton.disabled = !mayAnalyze;
    els.startGraspButton.disabled = !mayStart;
    const validationReady = pipeline.state === "GRASP_PLANNING"
      && ["GRASP_READY", "PLANNING_REJECTED"].includes(graspPlanningState?.status)
      && graspPlanningState?.simulation_attempt?.available === true
      && els.robotSelect.value === "panda"
      && !validationRunning;
    els.startValidationButton.disabled = !validationReady;
    els.validationScenarioSelect.disabled = validationRunning;
    if (mayStart) {
      els.startGraspLabel.textContent = "开始抓取";
      els.startGraspHint.textContent = "Start Grasp";
    } else if (["SCENE_CAPTURED", "SPATIAL_ANALYSIS"].includes(pipeline.state)) {
      els.startGraspLabel.textContent = "空间分析中";
      els.startGraspHint.textContent = "Spatial Analysis";
    } else if (pipeline.state === "SPATIAL_READY") {
      els.startGraspLabel.textContent = "空间感知就绪";
      els.startGraspHint.textContent = "Spatial Ready";
    } else if (pipeline.state === "GRASP_PLANNING" && graspPlanningState?.status === "GRASP_READY") {
      els.startGraspLabel.textContent = "抓取计划就绪";
      els.startGraspHint.textContent = "Grasp Ready";
    } else if (pipeline.state === "GRASP_PLANNING") {
      els.startGraspLabel.textContent = "抓取规划中";
      els.startGraspHint.textContent = "Grasp Planning";
    } else if (["SCENE_SYNC", "SIMULATION", "VERIFIED"].includes(pipeline.state)) {
      els.startGraspLabel.textContent = "仿真验证";
      els.startGraspHint.textContent = "Simulation Validation";
    } else {
      els.startGraspLabel.textContent = "请选择目标";
      els.startGraspHint.textContent = "Select Target";
    }
  }

  function setTargetOverlayVisible(visible) {
    if (visible) els.targetOverlay.removeAttribute("hidden");
    else els.targetOverlay.setAttribute("hidden", "");
  }

  function renderTargetHitboxes(state) {
    els.targetOverlay.replaceChildren();
    const frame = state?.overlay_frame || state?.frame;
    const tracking = state?.tracking;
    const candidates = tracking && state?.selected_target
      ? [{
          id: tracking.target_id,
          bbox_xyxy: tracking.bbox_xyxy,
          mask_polygon: tracking.mask_polygon,
          class_name: state.selected_target.class_name,
        }]
      : Array.isArray(state?.candidates) ? state.candidates : [];
    if (!frame || !candidates.length) {
      setTargetOverlayVisible(false);
      return;
    }
    els.targetOverlay.setAttribute("viewBox", `0 0 ${frame.width} ${frame.height}`);
    els.targetOverlay.setAttribute("preserveAspectRatio", "xMidYMid meet");
    const hitSurface = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    hitSurface.classList.add("target-hit-surface");
    hitSurface.setAttribute("x", "0");
    hitSurface.setAttribute("y", "0");
    hitSurface.setAttribute("width", String(frame.width));
    hitSurface.setAttribute("height", String(frame.height));
    els.targetOverlay.append(hitSurface);
    candidates.forEach((candidate, index) => {
      const [x1, y1, x2, y2] = candidate.bbox_xyxy;
      const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
      const box = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      const polygonPoints = Array.isArray(candidate.mask_polygon) ? candidate.mask_polygon : [];
      group.classList.add("target-candidate");
      if (candidate.id === state.selected_target_id || tracking) group.classList.add("is-selected");
      else if (state.selected_target_id) group.classList.add("is-dimmed");
      group.setAttribute("role", "button");
      group.setAttribute("tabindex", "0");
      group.setAttribute("aria-label", `选择候选 ${index + 1} ${candidate.class_name}`);
      box.setAttribute("x", String(x1));
      box.setAttribute("y", String(y1));
      box.setAttribute("width", String(x2 - x1));
      box.setAttribute("height", String(y2 - y1));
      box.setAttribute("rx", "4");
      if (polygonPoints.length >= 3) {
        const polygon = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
        polygon.setAttribute("points", polygonPoints.map(([x, y]) => `${x},${y}`).join(" "));
        group.append(polygon);
      }
      group.append(box);
      const label = candidate.class_name || "未知目标 Unknown Object";
      const displayLabel = tracking ? `${label} · 目标跟踪 Tracking` : label;
      const fontSize = Math.max(18, frame.width * 0.018);
      const labelY = Math.max(fontSize * 1.8, y1);
      const labelBackground = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      labelBackground.classList.add("target-label-bg");
      labelBackground.setAttribute("x", String(x1));
      labelBackground.setAttribute("y", String(labelY - fontSize * 1.45));
      labelBackground.setAttribute("width", String(Math.min(frame.width - x1, displayLabel.length * fontSize * 0.61 + 18)));
      labelBackground.setAttribute("height", String(fontSize * 1.55));
      labelBackground.setAttribute("rx", "3");
      const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
      text.textContent = displayLabel;
      text.setAttribute("x", String(x1 + 9));
      text.setAttribute("y", String(labelY - fontSize * 0.3));
      text.style.fontSize = `${fontSize}px`;
      group.append(labelBackground, text);
      group.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          event.stopPropagation();
          selectTarget(candidate.id);
        }
      });
      els.targetOverlay.append(group);
    });
    setTargetOverlayVisible(true);
  }

  function renderTargetPerception(state) {
    if (!state || state.schema_version !== TARGET_PERCEPTION_SCHEMA_VERSION) {
      throw new Error("Target Perception API 版本不匹配");
    }
    targetPerceptionState = state;
    renderConditionReport(state.condition_report);
    const candidates = Array.isArray(state.candidates) ? state.candidates : [];
    const selected = state.selected_target;
    const frame = state.frame;
    renderTargetHitboxes(state);
    els.analysisControls.hidden = !cameraShouldStream && !selected;
    els.analysisStatus.textContent = state.message || "扫描中 Scanning";
    els.visionScanFx.classList.toggle("is-scanning", !selected && cameraShouldStream);
    els.targetLockBanner.hidden = !selected;
    if (selected) {
      els.liveState.textContent = state.tracking ? "目标跟踪 Tracking" : "目标已锁定 Target Locked";
      els.targetStatus.textContent = "目标已锁定 Target Locked";
      els.targetValue.textContent = selected.id;
      els.targetClassValue.textContent = selected.class_name || "未知目标 Unknown Object";
      els.targetLockValue.textContent = state.tracking ? "目标跟踪 Tracking" : "目标已锁定 Target Locked";
      els.targetDetail.textContent = `源帧 Frame ${selected.source_frame_id} · 手动选择 Manual Selection · 高清叠加 HD Overlay`;
    } else {
      els.liveState.textContent = "扫描中 Scanning";
      els.targetStatus.textContent = state.status === "NO_CANDIDATES" ? "未发现目标 No Candidates" : candidates.length ? "可选择 Selectable" : "扫描中 Scanning";
      els.targetValue.textContent = candidates.length ? `${candidates.length} 个候选 Candidates` : "等待选择 WAITING";
      els.targetClassValue.textContent = candidates.length ? "未知目标 Unknown Object" : "暂无目标 No Target";
      els.targetLockValue.textContent = candidates.length ? "等待选择 Selectable" : "扫描中 Scanning";
      els.targetDetail.textContent = candidates.length
        ? "点击高清实时画面中的目标框以锁定目标。"
        : state.status === "NO_CANDIDATES"
          ? "当前实时画面未发现有效目标，系统将继续扫描。"
          : "连接手机后自动扫描实时 RGB 画面。";
    }
    if (frame) {
      els.liveResolution.textContent = `${frame.width} × ${frame.height}`;
      els.liveSourceLabel.textContent = `手机 Phone · 高清实时视觉 HD Live RGB`;
    }
    updateActionButtons();
  }

  function renderConditionReport(report) {
    if (!report) {
      els.conditionStatus.textContent = "等待评估 Waiting";
      els.conditionVisualValue.textContent = "尚未评估 Not Assessed";
      els.conditionLevelValue.textContent = "未启用 Disabled";
      els.conditionQualityValue.textContent = "暂无数据 Unavailable";
      els.conditionEnhancementValue.textContent = "暂无数据 Unavailable";
      els.conditionReliabilityValue.textContent = "暂无数据 Unavailable";
      els.conditionDetail.textContent = "等待运行视觉条件实验 Waiting for Condition Experiment。";
      els.conditionFrameChain.textContent = "原始图像 Raw Frame → 退化图像 Degraded Frame → 增强图像 Enhanced Frame → 流程图像 Pipeline Frame";
      return;
    }
    const quality = Number(report.image_quality_score);
    const blur = Number(report.blur_score);
    const brightness = Number(report.brightness_score);
    const stress = report.stress_test;
    const degradationChain = Array.isArray(stress?.degradation_chain)
      ? stress.degradation_chain.map((item) => CONDITION_CHAIN_LABELS[item] || item)
      : [];
    const enhancementChain = Array.isArray(report.enhancement_chain)
      ? report.enhancement_chain.map((item) => CONDITION_CHAIN_LABELS[item] || item)
      : [];
    const chain = [...degradationChain, ...enhancementChain].length
      ? [...degradationChain, ...enhancementChain].join(" → ")
      : "原始图像评估 Raw Assessment";
    const warnings = Array.isArray(report.uncertainty_hint) && report.uncertainty_hint.length
      ? ` · 风险提示 Warnings ${report.uncertainty_hint.map((item) => CONDITION_WARNING_LABELS[item] || item).join(" + ")}`
      : "";
    const rawId = stress?.frames?.raw?.frame_id ?? report.raw_frame_id;
    const degradedId = stress?.frames?.degraded?.frame_id ?? report.degraded_frame_id;
    const enhancedId = stress?.frames?.enhanced?.frame_id ?? "—";
    const pipelineId = stress?.frames?.pipeline?.frame_id ?? report.processed_frame_id;
    els.conditionStatus.textContent = "已评估 Assessed";
    els.conditionVisualValue.textContent = CONDITION_LABELS[report.condition_type] || report.condition_type;
    els.conditionLevelValue.textContent = stress?.stress_applied
      ? `${STRESS_LEVEL_LABELS[stress.level] || stress.level} · ${STRESS_STRATEGY_LABELS[stress.strategy] || stress.strategy}`
      : "未启用 Disabled";
    els.conditionQualityValue.textContent = Number.isFinite(quality) ? quality.toFixed(2) : "暂无数据 Unavailable";
    els.conditionEnhancementValue.textContent = ENHANCEMENT_LABELS[report.enhancement_status] || report.enhancement_status;
    els.conditionReliabilityValue.textContent = RELIABILITY_LABELS[report.reliability] || report.confidence_hint || "暂无数据 Unavailable";
    els.conditionDetail.textContent = els.graspModeSelect.value === "RESEARCH"
      ? `模糊评分 Blur ${blur.toFixed(2)} · 亮度评分 Brightness ${brightness.toFixed(2)} · ${chain} · 原始 Raw ${rawId} → 退化 Degraded ${degradedId} → 增强 Enhanced ${enhancedId} → 流程 Pipeline ${pipelineId}${warnings}`
      : `${CONDITION_LABELS[report.visual_condition] || report.visual_condition} · 图像质量 Quality ${quality.toFixed(2)} · ${RELIABILITY_LABELS[report.reliability] || report.reliability}`;
    els.conditionFrameChain.textContent = `原始图像 Raw Frame ${rawId} → 退化图像 Degraded Frame ${degradedId} → 增强图像 Enhanced Frame ${enhancedId} → 流程图像 Pipeline Frame ${pipelineId}`;
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
    if (state === "SPATIAL_READY" && spatialPerceptionState?.status === "READY") {
      const total = timingSeconds(spatialPerceptionState.timing?.total_s);
      els.systemStatus.textContent = total === "—" ? "READY" : `READY · ${total}`;
    } else if (state === "SPATIAL_ANALYSIS" && ["QUEUED", "ANALYZING"].includes(spatialPerceptionState?.status)) {
      const elapsed = timingSeconds(spatialPerceptionState.timing?.elapsed_s);
      els.systemStatus.textContent = elapsed === "—" ? "PROCESSING" : `PROCESSING · ${elapsed}`;
    } else {
      els.systemStatus.textContent = state === "LIVE" ? "READY" : state;
    }
    [els.spatialState, els.graspState, els.simulationState].forEach((element) => element.classList.remove("is-active"));
    if (["SPATIAL_ANALYSIS", "SPATIAL_READY"].includes(state)) els.spatialState.classList.add("is-active");
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
    els.spatialMediaLabels.hidden = true;
    els.spatialPendingOverlay.classList.remove("is-error");
    els.spatialProgressTitle.textContent = "空间分析 Spatial Analysis";
    els.spatialProgressDetail.textContent = "等待计算 WAITING";
    els.spatialLoadingIndicator.hidden = false;
    els.spatialElapsed.textContent = "Processing";
    els.spatialEta.textContent = "正在估计耗时 Estimating...";
    els.spatialDownloadProgress.hidden = true;
    els.spatialSlowWarning.hidden = true;
    els.spatialModelState.textContent = "Model Pending";
    els.spatialTimingSummary.hidden = true;
    els.spatialErrorActions.hidden = true;
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
    els.targetLockValue.textContent = "WAITING";
    els.targetDetail.textContent = "连接手机后自动扫描实时 RGB 画面。";
    renderConditionReport(null);
    els.spatialInspectorStatus.textContent = "WAITING";
    els.spatialDepthValue.textContent = "等待计算 WAITING";
    els.spatialValue.textContent = "NOT AVAILABLE";
    els.spatialSourceValue.textContent = "NOT AVAILABLE";
    els.spatialModeValue.textContent = "NOT AVAILABLE";
    els.spatialProjectionValue.textContent = "NOT AVAILABLE";
    els.spatialDetail.textContent = "Depth、XYZ 与 Point Cloud 均不可用。";
    els.graspInspectorStatus.textContent = "WAITING";
    els.graspValue.textContent = "等待规划 WAITING";
    els.graspAngleValue.textContent = "NOT AVAILABLE";
    els.graspWidthValue.textContent = "NOT AVAILABLE";
    els.graspQualityValue.textContent = "NOT AVAILABLE";
    els.graspApproachValue.textContent = "NOT AVAILABLE";
    els.graspFrameValue.textContent = "NOT AVAILABLE";
    els.graspDetail.textContent = "真实规划结果尚不可用。";
    els.graspPendingOverlay.hidden = true;
    els.graspLayerControls.hidden = true;
    els.graspElapsed.textContent = "Elapsed —";
    els.graspEta.textContent = "ETA Estimating...";
    els.simulationHud.hidden = true;
    els.simulationPlaybackControls.hidden = true;
    els.simulationHudState.textContent = "WAITING";
    els.simulationCollision.textContent = "CLEAR";
    els.simulationLift.textContent = "0.000 m";
    els.simulationTarget.textContent = "—";
    els.simulationAppearance.textContent = "WAITING";
    els.simulationTexture.textContent = "WAITING";
    els.simulationAppearanceSource.textContent = "Target Snapshot Frame —";
    els.simulationResult.textContent = "SIMULATION ONLY";
    els.simulationResult.className = "simulation-result";
    els.simulationPlanningResult.textContent = "WAITING";
    els.simulationPlanningResult.className = "";
    els.simulationPlanningReason.textContent = "Reason —";
    els.simulationAttemptState.textContent = "WAITING";
    els.simulationAttemptState.className = "";
    els.simulationAttemptCandidate.textContent = "Candidate —";
    els.startValidationButton.disabled = true;
    els.statusSnapshot.textContent = "WAITING";
    els.legacyRunStatus.textContent = "尚未载入 NOT LOADED";
    targetPerceptionState = null;
    spatialPerceptionState = null;
    graspPlanningState = null;
    validationState = null;
    spatialAnalysisRunning = false;
    activeSpatialJobId = null;
    graspPlanningRunning = false;
    activeGraspJobId = null;
    graspLayer = "candidates";
    validationRunning = false;
    simulationStreamStarted = false;
    window.clearInterval(validationTimer);
    window.clearTimeout(playbackSeekTimer);
    validationTimer = 0;
    analysisFrozen = false;
    targetAnalysisRunning = false;
    targetAnalysisRequest += 1;
    els.targetOverlay.replaceChildren();
    setTargetOverlayVisible(false);
    els.visionScanFx.classList.remove("is-scanning");
    els.targetLockBanner.hidden = true;
    els.analysisControls.hidden = true;
    els.analysisStatus.textContent = "扫描中 Scanning";
    updateActionButtons();
  }

  function startLiveView() {
    if (analysisFrozen || liveStreamStarted || workspaceMode !== "phone" || els.sourceSelect.value !== "phone") return;
    liveStreamStarted = true;
    els.liveMedia.src = liveConditionUrl("pipeline");
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

  function stopLiveVisionLoop() {
    window.clearTimeout(liveVisionTimer);
    liveVisionTimer = 0;
    els.visionScanFx.classList.remove("is-scanning");
  }

  function scheduleLiveVision(delay = 0) {
    if (
      liveVisionTimer
      || liveVisionRunning
      || targetAnalysisRunning
      || !cameraShouldStream
      || workspaceMode !== "phone"
      || els.sourceSelect.value !== "phone"
    ) return;
    liveVisionTimer = window.setTimeout(() => {
      liveVisionTimer = 0;
      refreshLiveVision().catch(() => {});
    }, delay);
  }

  async function refreshLiveVision({ forceScan = false } = {}) {
    if (liveVisionRunning || targetAnalysisRunning || !cameraShouldStream || workspaceMode !== "phone") return;
    const locked = targetPerceptionState?.status === "TARGET_LOCKED";
    if (!locked && pipeline.state !== "LIVE") return;
    liveVisionRunning = true;
    targetAnalysisRunning = !locked;
    const requestRevision = targetAnalysisRequest;
    if (!locked) {
      els.analysisControls.hidden = false;
      els.analysisStatus.textContent = "扫描中 Scanning";
      els.visionScanFx.classList.add("is-scanning");
    }
    updateActionButtons();
    try {
      const state = locked && !forceScan
        ? await apiPost("/api/target-perception/track", conditionExperimentSettings())
        : await apiPost("/api/target-perception/analyze", conditionExperimentSettings());
      if (requestRevision !== targetAnalysisRequest) return;
      analysisFrozen = false;
      renderTargetPerception(state);
    } catch (error) {
      if (!locked) {
        els.analysisStatus.textContent = `扫描暂不可用 Scan Unavailable · ${error.message}`;
        els.visionScanFx.classList.remove("is-scanning");
      }
    } finally {
      liveVisionRunning = false;
      targetAnalysisRunning = false;
      updateActionButtons();
      const remainsLocked = targetPerceptionState?.status === "TARGET_LOCKED";
      if (remainsLocked) scheduleLiveVision(180);
      else if (targetPerceptionState?.status !== "CANDIDATES") scheduleLiveVision(650);
    }
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
      const locked = targetPerceptionState?.status === "TARGET_LOCKED";
      els.liveState.textContent = locked
        ? "目标跟踪 Tracking"
        : live ? "扫描中 Scanning" : paired ? "已配对 Paired" : "未连接 Disconnected";
      els.liveState.classList.toggle("is-live", live || locked);
      els.liveSourceLabel.textContent = live
        ? "手机 Phone · 高清实时视觉 HD Live RGB"
        : "手机 Phone · 等待连接";
      els.liveResolution.textContent = resolution;
      els.liveConnection.textContent = cameraConnectionLabel(connection.status);
      els.statusConnection.textContent = live ? "实时 Live" : paired ? "已配对 Paired" : "未连接 Disconnected";
      updateActionButtons();
      if (live && !analysisFrozen) {
        startLiveView();
        if (targetPerceptionState?.status !== "CANDIDATES") {
          scheduleLiveVision(targetPerceptionState ? 180 : 0);
        }
      }
      else if (!live && liveStreamStarted) stopLiveView();
      if (!live) stopLiveVisionLoop();
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
        updateActionButtons();
        els.analyzeTargetsButton.disabled = true;
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
    analysisFrozen = false;
    if (cameraShouldStream) startLiveView();
    els.liveState.textContent = state.status === "TARGET_LOCKED" ? "目标已锁定 Target Locked" : "扫描中 Scanning";
    els.liveState.classList.add("is-live");
    renderTargetPerception(state);
    if (els.conditionDialog.open) renderConditionComparison();
  }

  async function analyzeTargets() {
    if (targetAnalysisRunning || pipeline.state !== "LIVE" || !cameraIsLive()) return;
    const requestRevision = ++targetAnalysisRequest;
    targetAnalysisRunning = true;
    els.analysisControls.hidden = false;
    els.analysisStatus.textContent = "扫描中 Scanning";
    els.visionScanFx.classList.add("is-scanning");
    els.analyzeTargetsButton.querySelector("span").textContent = "扫描中…";
    els.analyzeTargetsButton.querySelector("small").textContent = "Scanning";
    updateActionButtons();
    try {
      const state = await apiPost("/api/target-perception/analyze", {
        ...conditionExperimentSettings(),
      });
      if (requestRevision !== targetAnalysisRequest) return;
      analysisFrozen = false;
      renderTargetPerception(state);
      showNotice(state.status === "NO_CANDIDATES"
        ? "当前实时画面未发现目标，系统将继续扫描。"
        : `实时检测已更新，发现 ${state.candidates.length} 个可选目标。`,
      state.status === "NO_CANDIDATES" ? "error" : "success");
    } catch (error) {
      if (requestRevision !== targetAnalysisRequest) return;
      analysisFrozen = false;
      showNotice(`实时扫描失败：${error.message}`, "error");
    } finally {
      targetAnalysisRunning = false;
      els.analyzeTargetsButton.querySelector("span").textContent = "立即扫描";
      els.analyzeTargetsButton.querySelector("small").textContent = "Scan Now";
      updateActionButtons();
      if (targetPerceptionState?.status !== "CANDIDATES") scheduleLiveVision(650);
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
      analysisFrozen = false;
      renderTargetPerception(state);
      if (pipeline.state === "LIVE") {
        pipeline.transition("TARGET_SELECTED", {
          targetId: state.selected_target_id,
          sourceFrameId: state.frame.id,
          sourceTimestampS: state.frame.timestamp_s,
        });
      }
      updateActionButtons();
      showNotice(`目标已锁定 Target Locked · ${state.selected_target.class_name}`);
      window.setTimeout(() => startGrasp(), 650);
    } catch (error) {
      showNotice(`无法选择目标：${error.message}`, "error");
    }
  }

  async function selectTargetAtPointer(event) {
    if (
      event.button !== 0
      || !canSelectFrozenTarget(pipeline.state, targetPerceptionState)
    ) return;
    const sourcePoint = clientPointToSource(
      { clientX: event.clientX, clientY: event.clientY },
      els.liveMedia.getBoundingClientRect(),
      targetPerceptionState.frame,
    );
    if (!sourcePoint) return;
    event.preventDefault();
    event.stopPropagation();
    const frameId = targetPerceptionState.frame.id;
    const requestRevision = targetAnalysisRequest;
    els.targetOverlay.classList.add("is-selecting");
    try {
      const state = await apiPost("/api/target-perception/select-at", {
        source_x: sourcePoint.x,
        source_y: sourcePoint.y,
        source_frame_id: frameId,
      });
      if (requestRevision !== targetAnalysisRequest) return;
      analysisFrozen = false;
      renderTargetPerception(state);
      if (pipeline.state === "LIVE") {
        pipeline.transition("TARGET_SELECTED", {
          targetId: state.selected_target_id,
          sourceFrameId: state.frame.id,
          sourceTimestampS: state.frame.timestamp_s,
        });
      }
      updateActionButtons();
      showNotice(`目标已锁定 Target Locked · ${state.selected_target.class_name}`);
      window.setTimeout(() => startGrasp(), 650);
    } catch (error) {
      showNotice(`未选择目标：${error.message}`, "error");
    } finally {
      els.targetOverlay.classList.remove("is-selecting");
    }
  }

  async function restoreTargetPerceptionState() {
    try {
      const state = await apiGet(`/api/target-perception/state?t=${Date.now()}`);
      if (!["CANDIDATES", "TARGET_LOCKED"].includes(state.status) || !state.frame) return;
      showFrozenTargetFrame(state);
      if (state.status === "TARGET_LOCKED" && pipeline.state === "LIVE") {
        pipeline.transition("TARGET_SELECTED", {
          targetId: state.selected_target_id,
          sourceFrameId: state.frame.id,
          sourceTimestampS: state.frame.timestamp_s,
          restored: true,
        });
      }
    } catch { /* a clean workspace does not require persisted target state */ }
  }

  async function restoreSpatialPerceptionState() {
    if (pipeline.state !== "TARGET_SELECTED" || !targetPerceptionState?.scene_snapshot) return;
    try {
      const state = await apiGet(`/api/spatial-perception/state?t=${Date.now()}`);
      const snapshot = targetPerceptionState.scene_snapshot;
      const binding = state?.binding;
      const bindingMatches = Boolean(state?.job_id
        && binding?.job_id === state.job_id
        && binding?.snapshot_id === snapshot.snapshot_id
        && binding?.source_frame_id === snapshot.source_frame_id
        && binding?.target_instance_id === snapshot.target_id
        && binding?.source_timestamp_s === snapshot.source_timestamp_s);
      const readyMatches = hasSpatialObservationAssociation(targetPerceptionState, state);
      if (!bindingMatches && !readyMatches) return;
      pipeline.transition("SCENE_CAPTURED", {
        restored: true,
        snapshotId: snapshot.snapshot_id,
        targetId: snapshot.target_id,
        sourceFrameId: snapshot.source_frame_id,
      });
      pipeline.transition("SPATIAL_ANALYSIS", {
        restored: true,
        snapshotId: snapshot.snapshot_id,
        targetId: snapshot.target_id,
        sourceFrameId: snapshot.source_frame_id,
      });
      renderSpatialPerception(state);
      if (readyMatches) {
        pipeline.transition("SPATIAL_READY", {
          restored: true,
          snapshotId: snapshot.snapshot_id,
          targetId: snapshot.target_id,
          sourceFrameId: snapshot.source_frame_id,
        });
        els.statusSnapshot.textContent = `Frame ${snapshot.source_frame_id} · 已恢复 Restored`;
        return;
      }
      if (["QUEUED", "ANALYZING"].includes(state.status)) {
        spatialAnalysisRunning = true;
        activeSpatialJobId = state.job_id;
        updateActionButtons();
        void monitorRestoredSpatialJob(snapshot, state.job_id);
      }
    } catch { /* stale or incomplete spatial state must not advance the pipeline */ }
  }

  async function restoreGraspAndValidationState() {
    if (pipeline.state !== "SPATIAL_READY" || !spatialPerceptionState?.observation) return;
    try {
      const graspState = await apiGet(`/api/grasp-planning/state?t=${Date.now()}`);
      if (!hasGraspOutcomeAssociation(spatialPerceptionState, graspState)) return;
      pipeline.transition("GRASP_PLANNING", { restored: true });
      renderGraspPlanning(graspState);
      const simulationState = await apiGet(`/api/mujoco-validation/state?t=${Date.now()}`);
      const attemptTarget = simulationState.request?.simulation_attempt?.target_id;
      const graspTarget = graspState.plan?.target_id || graspState.candidates?.[0]?.target_instance_id;
      if (!simulationState.request || attemptTarget !== graspTarget) return;
      pipeline.transition("SCENE_SYNC", { restored: true });
      pipeline.transition("SIMULATION", { restored: true });
      if (simulationState.media?.stream_available) {
        els.simulationMedia.src = `/api/mujoco-validation/live.mjpeg?opened=${Date.now()}`;
        els.simulationMedia.hidden = false;
        els.simulationEmpty.hidden = true;
        simulationStreamStarted = true;
      }
      validationRunning = !["SUCCESS", "FAILED"].includes(simulationState.status);
      renderValidation(simulationState);
      if (validationRunning) validationTimer = window.setInterval(pollValidationState, 160);
    } catch { /* stale downstream state must not advance the restored pipeline */ }
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

  function depthModeLabel(mode) {
    if (mode === "METRIC") return "米制 Metric";
    if (mode === "APPROX_METRIC") return "近似米制 Approx. Metric";
    if (mode === "RELATIVE") return "相对深度 Relative";
    return "NOT AVAILABLE";
  }

  function timingSeconds(value) {
    const seconds = Number(value);
    return Number.isFinite(seconds) && seconds >= 0 ? `${seconds.toFixed(1)} s` : "—";
  }

  function formatBytes(value) {
    const bytes = Number(value);
    if (!Number.isFinite(bytes) || bytes < 0) return "—";
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function spatialEtaLabel(state) {
    const downloadEta = Number(state?.download?.download_eta_s);
    if (state?.stage === "MODEL_DOWNLOADING" && Number.isFinite(downloadEta)) {
      return `下载 ETA（估计）· 约 ${Math.ceil(downloadEta)} s`;
    }
    const eta = Number(state?.eta?.estimated_remaining_s);
    if (state?.eta?.available && Number.isFinite(eta)) {
      return `预计剩余（本机历史估计）· 约 ${Math.ceil(eta)} s`;
    }
    return "正在估计耗时 Estimating...";
  }

  function renderSpatialTimingSummary(state) {
    const timing = state?.timing || {};
    const total = Number(timing.total_s);
    const totalLabel = timingSeconds(total);
    els.spatialReadyTiming.textContent = Number.isFinite(total) ? `READY · ${totalLabel}` : "READY";
    els.spatialModelLoadTiming.textContent = timing.model_was_ready
      ? "Model Ready"
      : timingSeconds(timing.model_load_s);
    els.spatialDepthTiming.textContent = timingSeconds(timing.depth_inference_s);
    els.spatialPointCloudTiming.textContent = timingSeconds(timing.point_cloud_s);
    els.spatialComputeTiming.textContent = timingSeconds(timing.spatial_computing_s);
    els.spatialTotalTiming.textContent = totalLabel;
    els.spatialTimingSummary.hidden = false;
  }

  function renderSpatialPerception(state) {
    if (!state || state.schema_version !== SPATIAL_PERCEPTION_SCHEMA_VERSION) {
      throw new Error("Spatial Perception API 版本不匹配");
    }
    spatialPerceptionState = state;
    const observation = state.observation;
    if (state.status === "READY" && observation) {
      const unit = observation.unit === "m" ? "m" : "relative";
      const xyz = Array.isArray(observation.centroid_xyz) ? observation.centroid_xyz : null;
      if (!xyz || xyz.length !== 3 || !xyz.every((value) => Number.isFinite(Number(value)))) {
        throw new Error("Spatial Observation 缺少有效 Target XYZ");
      }
      els.spatialSnapshot.src = `/api/spatial-perception/overview.jpg?revision=${state.revision}`;
      els.spatialSnapshot.hidden = false;
      els.spatialMediaLabels.hidden = false;
      els.spatialEmpty.hidden = true;
      els.spatialPendingOverlay.hidden = true;
      renderSpatialTimingSummary(state);
      els.spatialPendingOverlay.classList.remove("is-error");
      els.spatialErrorActions.hidden = true;
      const totalLabel = timingSeconds(state.timing?.total_s);
      els.spatialState.textContent = totalLabel === "—" ? "READY" : `READY · ${totalLabel}`;
      els.spatialState.classList.add("has-data");
      els.spatialInspectorStatus.textContent = els.spatialState.textContent;
      els.spatialDepthValue.textContent = `${Number(observation.target_depth).toFixed(3)} ${unit}`;
      els.spatialValue.textContent = `X ${Number(xyz[0]).toFixed(3)} · Y ${Number(xyz[1]).toFixed(3)} · Z ${Number(xyz[2]).toFixed(3)} ${unit}`;
      els.spatialSourceValue.textContent = observation.depth_source === "RGBD" ? "RGB-D 相机 RGB-D" : "单目 Monocular";
      els.spatialModeValue.textContent = depthModeLabel(observation.depth_mode);
      els.spatialProjectionValue.textContent = observation.intrinsics_source === "NOMINAL_FOV"
        ? "标称视场角 Nominal FOV · 未标定"
        : "已标定 Calibrated";
      const quality = observation.quality || {};
      const validRatio = Number(quality.valid_depth_ratio);
      const qualityText = Number.isFinite(validRatio) ? `${(validRatio * 100).toFixed(1)}% 有效深度` : "有效深度已验证";
      els.spatialDetail.textContent = `相机坐标系 Camera Frame · ${observation.point_count} 个真实目标点 · ${qualityText}`;
      els.spatialFooter.textContent = `FRAME ${observation.source_frame_id} · ${observation.target_instance_id}`;
      els.systemStatus.textContent = els.spatialState.textContent;
      return;
    }

    if (["FAILED", "CANCELLED"].includes(state.status)) {
      const errorLabel = SPATIAL_ERROR_MESSAGES[state.error_code] || SPATIAL_ERROR_MESSAGES.SPATIAL_ANALYSIS_FAILED;
      els.spatialState.textContent = state.status;
      els.spatialState.classList.remove("has-data");
      els.spatialInspectorStatus.textContent = "ERROR";
      els.spatialDepthValue.textContent = "NOT AVAILABLE";
      els.spatialValue.textContent = "NOT AVAILABLE";
      els.spatialSourceValue.textContent = "NOT AVAILABLE";
      els.spatialModeValue.textContent = "NOT AVAILABLE";
      els.spatialProjectionValue.textContent = "NOT AVAILABLE";
      els.spatialDetail.textContent = `${errorLabel}；未生成 XYZ 或 Point Cloud。`;
      els.spatialFooter.textContent = state.error_code || "SPATIAL ERROR";
      els.spatialPendingOverlay.hidden = false;
      els.spatialPendingOverlay.classList.add("is-error");
      els.spatialLoadingIndicator.hidden = true;
      const loadFailed = [
        "DEPTH_UNAVAILABLE",
        "MODEL_NOT_FOUND",
        "DOWNLOAD_FAILED",
        "CHECKSUM_FAILED",
        "MODEL_LOAD_FAILED",
        "MODEL_LOAD_TIMEOUT",
      ].includes(state.error_code)
        && state.failed_stage === "MODEL_LOADING";
      els.spatialProgressTitle.textContent = loadFailed
        ? "DEPTH UNAVAILABLE"
        : "空间分析失败 SPATIAL ERROR";
      els.spatialProgressDetail.textContent = loadFailed
        ? `Model Loading Failed · ${state.message || errorLabel}`
        : `${errorLabel} · ${state.message || "No spatial output generated"}`;
      els.spatialElapsed.textContent = `Elapsed · ${timingSeconds(state.timing?.elapsed_s)}`;
      els.spatialEta.textContent = spatialEtaLabel(state);
      els.spatialDownloadProgress.hidden = true;
      els.spatialSlowWarning.hidden = true;
      els.spatialModelState.textContent = loadFailed ? "Model Loading Failed" : "No READY output";
      els.spatialTimingSummary.hidden = true;
      els.spatialErrorActions.hidden = false;
      els.systemStatus.textContent = state.error_code || "SPATIAL ERROR";
      return;
    }

    if (["QUEUED", "ANALYZING"].includes(state.status)) showSpatialAnalyzing(state);
  }

  function showSpatialAnalyzing(state = null) {
    els.spatialMediaLabels.hidden = true;
    els.spatialTimingSummary.hidden = true;
    els.spatialPendingOverlay.hidden = false;
    els.spatialPendingOverlay.classList.remove("is-error");
    els.spatialLoadingIndicator.hidden = false;
    els.spatialProgressTitle.textContent = "空间分析 Spatial Analysis";
    els.spatialProgressDetail.textContent = state?.stage_message || "正在准备场景 Scene Preparing...";
    const elapsed = timingSeconds(state?.total_elapsed_s ?? state?.timing?.elapsed_s);
    const stageElapsed = timingSeconds(state?.stage_elapsed_s);
    els.spatialElapsed.textContent = elapsed === "—"
      ? "Processing"
      : `已用时 Elapsed · ${elapsed} · Stage ${stageElapsed}`;
    els.spatialEta.textContent = spatialEtaLabel(state);
    const download = state?.download;
    const totalBytes = Number(download?.bytes_total);
    const downloadedBytes = Number(download?.bytes_downloaded);
    const hasKnownTotal = Number.isFinite(totalBytes) && totalBytes > 0;
    const hasDownload = state?.stage === "MODEL_DOWNLOADING" && Number.isFinite(downloadedBytes);
    els.spatialDownloadProgress.hidden = !hasDownload;
    if (hasDownload) {
      els.spatialDownloadBar.hidden = !hasKnownTotal;
      if (hasKnownTotal) {
        els.spatialDownloadBar.value = Math.max(0, Math.min(downloadedBytes / totalBytes, 1));
        els.spatialDownloadDetail.textContent = `${Math.round(downloadedBytes / totalBytes * 100)}% · ${formatBytes(downloadedBytes)} / ${formatBytes(totalBytes)}`;
      } else {
        els.spatialDownloadDetail.textContent = `已下载 ${formatBytes(downloadedBytes)}`;
      }
    }
    els.spatialSlowWarning.hidden = !state?.taking_longer;
    if (state?.taking_longer) {
      const range = state?.eta?.stage_typical_range_s;
      els.spatialSlowWarning.textContent = Array.isArray(range) && range.length === 2
        ? `运行时间异常 Taking Longer Than Expected · 通常 ${timingSeconds(range[0])}–${timingSeconds(range[1])}`
        : "运行时间异常 Taking Longer Than Expected";
    }
    els.spatialModelState.textContent = state?.model_state === "READY"
      ? "Model Ready"
      : state?.stage === "MODEL_LOADING" ? "Model Loading"
        : state?.cold_start ? "Cold Start" : "Warm Start";
    els.spatialErrorActions.hidden = true;
    els.spatialState.textContent = elapsed === "—" ? "ANALYZING" : `PROCESSING · ${elapsed}`;
    els.spatialState.classList.remove("has-data");
    els.spatialInspectorStatus.textContent = els.spatialState.textContent;
    els.spatialDepthValue.textContent = "正在计算 PROCESSING";
    els.spatialValue.textContent = "NOT AVAILABLE";
    els.spatialSourceValue.textContent = "单目 Monocular";
    els.spatialModeValue.textContent = "正在确认 CHECKING";
    els.spatialProjectionValue.textContent = "相机投影模型 Camera Projection Model";
    els.spatialDetail.textContent = "仅处理已冻结且与目标锁定关联的 Scene Snapshot。";
    els.systemStatus.textContent = els.spatialState.textContent;
  }

  function waitMilliseconds(value) {
    return new Promise((resolve) => window.setTimeout(resolve, value));
  }

  async function waitForSpatialJob(jobId) {
    while (spatialAnalysisRunning && activeSpatialJobId === jobId) {
      await waitMilliseconds(250);
      const state = await apiGet(`/api/spatial-perception/state?t=${Date.now()}`);
      if (state.job_id !== jobId) {
        throw new Error(`Spatial Job 已被替换：${jobId}`);
      }
      renderSpatialPerception(state);
      if (["READY", "FAILED", "CANCELLED"].includes(state.status)) return state;
    }
    throw new Error(`Spatial Job 已取消：${jobId}`);
  }

  async function monitorRestoredSpatialJob(snapshot, jobId) {
    try {
      const state = await waitForSpatialJob(jobId);
      renderSpatialPerception(state);
      if (state.status === "READY") {
        if (!hasSpatialObservationAssociation(targetPerceptionState, state)) {
          throw new Error("恢复的 Spatial Job 与当前 Scene Snapshot 关联不一致");
        }
        pipeline.transition("SPATIAL_READY", {
          restored: true,
          snapshotId: snapshot.snapshot_id,
          targetId: snapshot.target_id,
          sourceFrameId: snapshot.source_frame_id,
        });
        els.statusSnapshot.textContent = `Frame ${snapshot.source_frame_id} · 已恢复 Restored`;
        showNotice("空间感知后台任务已完成并恢复到当前 Workspace。", "success");
      } else {
        showNotice(SPATIAL_ERROR_MESSAGES[state.error_code] || "空间分析失败 SPATIAL ERROR", "error");
      }
    } catch (error) {
      renderSpatialPerception({
        schema_version: SPATIAL_PERCEPTION_SCHEMA_VERSION,
        status: "FAILED",
        error_code: "SPATIAL_ANALYSIS_FAILED",
        message: error.message,
        timing: {},
        observation: null,
      });
      showNotice(`空间分析恢复失败：${error.message}`, "error");
    } finally {
      if (activeSpatialJobId === jobId) activeSpatialJobId = null;
      spatialAnalysisRunning = false;
      updateActionButtons();
    }
  }

  async function runSpatialAnalysis({ retry = false } = {}) {
    const snapshot = targetPerceptionState?.scene_snapshot;
    if (spatialAnalysisRunning || !snapshot?.available || pipeline.state !== "SPATIAL_ANALYSIS") return;
    spatialAnalysisRunning = true;
    showSpatialAnalyzing();
    updateActionButtons();
    try {
      const initial = retry
        ? await apiPost("/api/spatial-perception/retry")
        : await apiPost("/api/spatial-perception/analyze", {
          snapshot_id: snapshot.snapshot_id,
          source_frame_id: snapshot.source_frame_id,
          target_instance_id: snapshot.target_id,
          source_timestamp_s: snapshot.source_timestamp_s,
        });
      if (!initial.job_id || initial.binding?.snapshot_id !== snapshot.snapshot_id
        || initial.binding?.source_frame_id !== snapshot.source_frame_id
        || initial.binding?.target_instance_id !== snapshot.target_id) {
        throw new Error("Spatial Job 与当前 Scene Snapshot / Frame / Target 绑定不一致");
      }
      activeSpatialJobId = initial.job_id;
      renderSpatialPerception(initial);
      const state = ["READY", "FAILED", "CANCELLED"].includes(initial.status)
        ? initial
        : await waitForSpatialJob(initial.job_id);
      renderSpatialPerception(state);
      if (state.status === "READY") {
        if (!hasSpatialObservationAssociation(targetPerceptionState, state)) {
          throw new Error("空间结果与冻结 Scene Snapshot 关联不一致");
        }
        pipeline.transition("SPATIAL_READY", {
          snapshotId: snapshot.snapshot_id,
          targetId: snapshot.target_id,
          sourceFrameId: snapshot.source_frame_id,
        });
        showNotice("空间感知完成：同一 Scene Snapshot 的 Depth、Point Cloud 与 Camera Frame XYZ 已生成，正在进入真实 Top-K 抓取规划。", "success");
      } else {
        showNotice(SPATIAL_ERROR_MESSAGES[state.error_code] || "空间分析失败 SPATIAL ERROR", "error");
      }
    } catch (error) {
      renderSpatialPerception({
        schema_version: SPATIAL_PERCEPTION_SCHEMA_VERSION,
        status: "FAILED",
        error_code: "SPATIAL_ANALYSIS_FAILED",
        message: error.message,
        timing: {},
        observation: null,
      });
      showNotice(`空间分析未完成：${error.message}`, "error");
    } finally {
      activeSpatialJobId = null;
      spatialAnalysisRunning = false;
      updateActionButtons();
    }
  }

  function vectorLabel(vector, digits = 3) {
    if (!Array.isArray(vector) || vector.length !== 3) return "NOT AVAILABLE";
    return `X ${Number(vector[0]).toFixed(digits)} · Y ${Number(vector[1]).toFixed(digits)} · Z ${Number(vector[2]).toFixed(digits)}`;
  }

  function renderGraspPlanning(state) {
    if (!state || state.schema_version !== GRASP_PLANNING_SCHEMA_VERSION) {
      throw new Error("Grasp Planning API 版本不匹配");
    }
    graspPlanningState = state;
    const plan = state.plan;
    const attempt = state.simulation_attempt || {};
    const attemptCandidate = Array.isArray(state.candidates) ? state.candidates[0] : null;
    els.simulationPlanningResult.textContent = state.status === "PLANNING_REJECTED"
      ? "REJECTED"
      : (state.status === "GRASP_READY" ? "GRASP_READY" : state.status || "WAITING");
    els.simulationPlanningResult.className = state.status === "PLANNING_REJECTED"
      ? "is-rejected"
      : (state.status === "GRASP_READY" ? "is-ready" : "");
    els.simulationPlanningReason.textContent = `Reason ${state.error_code || "—"}`;
    els.simulationAttemptState.textContent = attempt.available ? "READY" : "WAITING";
    els.simulationAttemptState.className = attempt.available ? "is-ready" : "";
    els.simulationAttemptCandidate.textContent = `Candidate ${attempt.candidate_id || "—"}`;
    const timing = state.timing || {};
    const elapsed = Number(timing.total_elapsed_s);
    els.graspElapsed.textContent = Number.isFinite(elapsed) ? `Elapsed ${elapsed.toFixed(2)} s` : "Elapsed —";
    els.graspEta.textContent = Number.isFinite(Number(timing.eta_s))
      ? `ETA ${Number(timing.eta_s).toFixed(1)} s`
      : "ETA Estimating...";
    if (state.status === "GRASP_READY" && plan) {
      if (!hasGraspPlanAssociation(spatialPerceptionState, state)) {
        throw new Error("GraspPlan 与 SpatialResult 关联不一致");
      }
      setGraspLayer(graspLayer);
      els.graspMedia.hidden = false;
      els.graspEmpty.hidden = true;
      els.graspPendingOverlay.hidden = true;
      els.graspLayerControls.hidden = false;
      els.graspState.textContent = "GRASP_READY";
      els.graspState.classList.add("has-data");
      els.graspInspectorStatus.textContent = "GRASP_READY";
      els.graspValue.textContent = `${vectorLabel(plan.grasp_point_xyz)} m`;
      els.graspAngleValue.textContent = `${Number(plan.grasp_angle_deg).toFixed(1)}°`;
      els.graspWidthValue.textContent = `${(Number(plan.gripper_width) * 1000).toFixed(1)} mm`;
      els.graspQualityValue.textContent = `${(Number(plan.quality_score) * 100).toFixed(1)} / 100`;
      els.graspApproachValue.textContent = vectorLabel(plan.approach_vector, 2);
      els.graspFrameValue.textContent = "相机坐标系 Camera Frame";
      const confidence = plan.confidence || {};
      const preflight = state.preflight || {};
      els.graspDetail.textContent = state.mode === "DEMO"
        ? `Graspability Preflight · ${preflight.executable_candidates || 0} 个可执行候选 · 同一真实算法`
        : `Top-K ${state.candidate_count} · Reject ${state.rejected_count} · 几何置信度 ${Number(confidence.value || 0).toFixed(2)} · Workspace Reachability UNKNOWN`;
      els.graspFooter.textContent = `${state.executable_count} EXECUTABLE / ${state.candidate_count} TOP-K · ${plan.best_candidate_id}`;
      updateActionButtons();
      return;
    }
    if (state.status === "PLANNING_REJECTED") {
      const rejectionLabel = graspRejectionLabel(state.error_code, state.mode);
      if (state.media?.overlay_available) {
        setGraspLayer("candidates");
        els.graspMedia.hidden = false;
        els.graspEmpty.hidden = true;
        els.graspLayerControls.hidden = false;
      }
      els.graspPendingOverlay.hidden = true;
      els.graspState.textContent = "REJECTED";
      els.graspState.classList.remove("has-data");
      els.graspInspectorStatus.textContent = "PLANNING_REJECTED";
      els.graspValue.textContent = attemptCandidate
        ? `尝试候选 ${attemptCandidate.candidate_id} · PLANNING REJECTED`
        : "没有候选 NO CANDIDATE";
      els.graspAngleValue.textContent = attemptCandidate
        ? `${Number(attemptCandidate.angle_deg).toFixed(1)}°`
        : "NOT AVAILABLE";
      els.graspWidthValue.textContent = attemptCandidate
        ? `${(Number(attemptCandidate.width_m) * 1000).toFixed(1)} mm`
        : "NOT AVAILABLE";
      els.graspQualityValue.textContent = attemptCandidate
        ? `${(Number(attemptCandidate.quality) * 100).toFixed(1)} / 100`
        : "NOT AVAILABLE";
      els.graspApproachValue.textContent = vectorLabel(attemptCandidate?.approach_direction, 2);
      els.graspFrameValue.textContent = attemptCandidate ? "相机坐标系 Camera Frame" : "NOT AVAILABLE";
      els.graspDetail.textContent = `${rejectionLabel} · ${state.rejected_count} 个真实候选被过滤 · Simulation Attempt ${attempt.available ? "READY" : "UNAVAILABLE"}`;
      els.graspFooter.textContent = attempt.available
        ? `PLANNING_REJECTED · ATTEMPT READY · ${attempt.candidate_id}`
        : `PLANNING_REJECTED · ${rejectionLabel}`;
      updateActionButtons();
      return;
    }
    if (state.status === "GRASP_ERROR") {
      els.graspState.textContent = "ERROR";
      els.graspState.classList.remove("has-data");
      els.graspInspectorStatus.textContent = "GRASP_ERROR";
      els.graspValue.textContent = "规划错误 ERROR";
      [els.graspAngleValue, els.graspWidthValue, els.graspQualityValue, els.graspApproachValue, els.graspFrameValue]
        .forEach((element) => { element.textContent = "NOT AVAILABLE"; });
      els.graspDetail.textContent = `${state.error_code || "GRASP_PLANNING_FAILED"} · ${state.message || "抓取规划错误"}`;
      els.graspFooter.textContent = state.error_code || "GRASP_ERROR";
      els.graspPendingOverlay.hidden = false;
      els.graspProgressTitle.textContent = "抓取规划错误 GRASP ERROR";
      els.graspProgressDetail.textContent = state.error_code || "PLANNING ERROR";
      updateActionButtons();
      return;
    }
    els.graspState.textContent = state.stage || "PLANNING";
    els.graspState.classList.remove("has-data");
    els.graspInspectorStatus.textContent = state.stage || "PLANNING";
    els.graspPendingOverlay.hidden = false;
    els.graspProgressTitle.textContent = "抓取规划 Grasp Planning";
    els.graspProgressDetail.textContent = state.stage || "QUEUED";
    els.graspFooter.textContent = state.job_id ? `JOB ${state.job_id.slice(-8)}` : "PROCESSING";
  }

  function setGraspLayer(layer) {
    const available = graspPlanningState?.media?.available_layers || [];
    const selected = available.includes(layer) ? layer : "candidates";
    graspLayer = selected;
    els.graspLayerControls.querySelectorAll("[data-grasp-layer]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.graspLayer === selected);
    });
    if (available.includes(selected)) {
      els.graspMedia.src = selected === "candidates"
        ? `/api/grasp-planning/overlay.jpg?revision=${graspPlanningState.revision}`
        : `/api/grasp-planning/view.jpg?layer=${encodeURIComponent(selected)}&revision=${graspPlanningState.revision}`;
    }
  }

  async function waitForGraspJob(jobId) {
    while (graspPlanningRunning && activeGraspJobId === jobId) {
      await waitMilliseconds(200);
      const state = await apiGet(`/api/grasp-planning/state?t=${Date.now()}`);
      if (state.job_id !== jobId) throw new Error(`Grasp Job 已被替换：${jobId}`);
      renderGraspPlanning(state);
      if (["GRASP_READY", "PLANNING_REJECTED", "GRASP_ERROR", "CANCELLED"].includes(state.status)) return state;
    }
    throw new Error("Grasp Job 已取消 CANCELLED");
  }

  async function runGraspPlanning() {
    if (graspPlanningRunning || pipeline.state !== "SPATIAL_READY") return;
    graspPlanningRunning = true;
    pipeline.transition("GRASP_PLANNING", { source: "spatial-result" });
    els.graspState.textContent = "PLANNING";
    els.graspInspectorStatus.textContent = "PLANNING";
    els.graspPendingOverlay.hidden = false;
    els.graspProgressTitle.textContent = "抓取规划 Grasp Planning";
    els.graspProgressDetail.textContent = "真实抓取图推理与 Top-K 规划 QUEUED";
    updateActionButtons();
    try {
      const initial = await apiPost("/api/grasp-planning/plan", {
        snapshot_id: spatialPerceptionState?.observation?.snapshot_id,
        mode: els.graspModeSelect.value,
      });
      if (!initial.job_id) throw new Error("Grasp Planning 未返回 job_id");
      activeGraspJobId = initial.job_id;
      renderGraspPlanning(initial);
      const state = ["GRASP_READY", "PLANNING_REJECTED", "GRASP_ERROR", "CANCELLED"].includes(initial.status)
        ? initial
        : await waitForGraspJob(initial.job_id);
      renderGraspPlanning(state);
      if (state.status === "GRASP_READY") {
        showNotice("抓取规划完成：真实 Top-K 已过滤并选出 Best Executable Grasp。", "success");
      } else if (state.status === "PLANNING_REJECTED") {
        showNotice(`规划拒绝：${graspRejectionLabel(state.error_code, state.mode)}；候选诊断已保留。`, "error");
      } else {
        showNotice(`抓取规划错误：${state.error_code || "GRASP_PLANNING_FAILED"}`, "error");
      }
    } catch (error) {
      renderGraspPlanning({
        schema_version: GRASP_PLANNING_SCHEMA_VERSION,
        status: "GRASP_ERROR",
        stage: "FAILED",
        error_code: "GRASP_PLANNING_FAILED",
        message: error.message,
        plan: null,
        timing: {},
        media: { available_layers: [] },
      });
      showNotice(`抓取规划未完成：${error.message}`, "error");
    } finally {
      activeGraspJobId = null;
      graspPlanningRunning = false;
      updateActionButtons();
    }
  }

  function renderValidation(state) {
    if (!state || state.schema_version !== MUJOCO_VALIDATION_SCHEMA_VERSION) {
      throw new Error("MuJoCo Validation API 版本不匹配");
    }
    const previousStatus = validationState?.status;
    validationState = state;
    const telemetry = state.telemetry || {};
    const result = state.result;
    const planningResult = state.planning_result || state.request?.planning_result;
    const simulationAttempt = state.request?.simulation_attempt;
    const recording = state.recording;
    const playback = state.playback;
    const targetLock = state.request?.target_lock_metadata || recording?.target_lock_metadata;
    if (targetLock) {
      els.targetStatus.textContent = "目标已锁定 Target Locked";
      els.targetValue.textContent = targetLock.target_id;
      els.targetLockValue.textContent = "记录已关联 Recording Linked";
      els.targetDetail.textContent = `锁定帧 Frame ${targetLock.frame_id} · 锁定时间 Lock Time ${targetLock.lock_timestamp}`;
    }
    els.simulationState.textContent = state.status;
    els.simulationState.classList.toggle("has-data", Boolean(state.media?.stream_available));
    els.simulationHud.hidden = !state.media?.stream_available;
    els.simulationHudState.textContent = telemetry.robot_state || state.status;
    els.simulationCollision.textContent = telemetry.collision ? "COLLISION" : "CLEAR";
    els.simulationCollision.classList.toggle("is-alert", Boolean(telemetry.collision));
    els.simulationTarget.textContent = telemetry.target_id || simulationAttempt?.target_id || "—";
    if (planningResult) {
      els.simulationPlanningResult.textContent = planningResult.status === "PLANNING_REJECTED"
        ? "REJECTED"
        : planningResult.status;
      els.simulationPlanningResult.className = planningResult.status === "PLANNING_REJECTED"
        ? "is-rejected"
        : "is-ready";
      els.simulationPlanningReason.textContent = `Reason ${planningResult.reason || "—"}`;
    }
    if (simulationAttempt) {
      els.simulationAttemptState.textContent = ["SUCCESS", "FAILED"].includes(state.status)
        ? state.status
        : "RUNNING";
      els.simulationAttemptState.className = state.status === "FAILED"
        ? "is-failed"
        : (state.status === "SUCCESS" ? "is-ready" : "");
      els.simulationAttemptCandidate.textContent = `Candidate ${simulationAttempt.candidate_id || "—"}`;
    }
    const appearance = telemetry.target_appearance
      || recording?.target_appearance
      || state.request?.target_appearance;
    const appearanceStatus = String(appearance?.appearance_status || "APPEARANCE_FALLBACK");
    const textureStatus = String(appearance?.texture_status || "FAILED");
    els.simulationAppearance.textContent = appearanceStatus === "REAL_RGB"
      ? "REAL RGB"
      : "APPEARANCE FALLBACK";
    els.simulationTexture.textContent = textureStatus === "PENDING_LOAD"
      ? "LOADING"
      : textureStatus;
    els.simulationTexture.classList.toggle("is-alert", textureStatus === "FAILED");
    const appearanceFrame = Number(appearance?.source_frame_id);
    els.simulationAppearanceSource.textContent = Number.isFinite(appearanceFrame)
      ? `Target Snapshot Frame ${appearanceFrame}`
      : "Target Snapshot Frame —";
    const initialZ = Number(state.request?.scene_transform?.target_position_world?.[2]);
    const currentZ = Number(telemetry.target_position_world?.[2]);
    const liveLift = Number.isFinite(initialZ) && Number.isFinite(currentZ) ? Math.max(0, currentZ - initialZ) : 0;
    els.simulationLift.textContent = `${Number(telemetry.lift_height_m ?? result?.lift_height_m ?? liveLift).toFixed(3)} m`;
    els.simulationFooter.textContent = `${state.scenario || "NOMINAL"} · ${state.camera_mode} · ${state.status}`;
    document.querySelectorAll("[data-sim-camera]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.simCamera === state.camera_mode);
    });
    const replayAvailable = Boolean(state.media?.replay_available && recording && playback);
    const visualizationAvailable = Boolean(state.media?.visualization_available && recording);
    const recordAvailable = replayAvailable || visualizationAvailable;
    els.simulationPlaybackControls.hidden = !recordAvailable;
    if (recordAvailable) {
      const currentTime = Number(playback?.current_time || 0);
      const duration = Number(playback?.duration_s || recording.duration_s || 0);
      const replayState = recording?.result?.state || state.status;
      els.recordingAvailability.textContent = replayAvailable
        ? `${["SUCCESS", "FAILED"].includes(replayState) ? replayState : "Simulation"} Replay · Available`
        : "Visualization Available";
      els.recordingSaveState.textContent = state.media.recording_saved ? "Saved" : "Unsaved";
      els.recordingSaveState.classList.toggle("is-saved", Boolean(state.media.recording_saved));
      els.saveRecordingButton.disabled = Boolean(state.media.recording_saved);
      els.saveRecordingButton.textContent = state.media.recording_saved ? "已保存 Saved" : "保存记录 Save Recording";
      els.playbackTimeline.max = String(Math.max(duration, 0.001));
      if (document.activeElement !== els.playbackTimeline) els.playbackTimeline.value = String(currentTime);
      els.playbackCurrentTime.textContent = currentTime.toFixed(3);
      els.playbackDuration.textContent = `${duration.toFixed(3)} s`;
      els.playPauseButton.dataset.playbackAction = playback?.paused !== false ? "PLAY" : "PAUSE";
      els.playPauseButton.textContent = playback?.paused !== false ? "▶ Play" : "Ⅱ Pause";
      document.querySelectorAll("[data-playback-speed]").forEach((button) => {
        button.classList.toggle("is-active", Number(button.dataset.playbackSpeed) === Number(playback?.playback_speed));
      });
      els.technicalOverlayToggle.checked = playback?.overlay_mode === "TECHNICAL";
      document.querySelectorAll("[data-playback-action], [data-playback-speed]").forEach((button) => {
        button.disabled = !replayAvailable;
      });
      els.playbackTimeline.disabled = !replayAvailable;
      els.technicalOverlayToggle.disabled = !replayAvailable;
      els.exportVideoButton.disabled = !replayAvailable;
    }
    if (["SUCCESS", "FAILED"].includes(state.status)) {
      validationRunning = false;
      els.simulationResult.textContent = state.status === "SUCCESS"
        ? "仿真验证成功 Simulation Validation SUCCESS"
        : `仿真验证失败 Simulation Validation FAILED · ${state.reason || "State Error"}`;
      els.simulationResult.className = `simulation-result is-${state.status.toLowerCase()}`;
      if (pipeline.state === "SIMULATION") {
        pipeline.transition("VERIFIED", { result: state.status, reason: state.reason || null });
      }
      if (previousStatus && previousStatus !== state.status) {
        showNotice(`${els.simulationResult.textContent} · Replay Available · Unsaved`, state.status === "SUCCESS" ? "success" : "error");
      }
      if (playback?.paused && validationTimer) {
        window.clearInterval(validationTimer);
        validationTimer = 0;
      }
    } else {
      els.simulationResult.textContent = "真实连续物理 REAL-TIME PHYSICS · SIMULATION ONLY";
      els.simulationResult.className = "simulation-result";
    }
    updateActionButtons();
  }

  function ensureValidationPolling() {
    if (!validationTimer) validationTimer = window.setInterval(pollValidationState, 120);
  }

  async function pollValidationState() {
    try {
      renderValidation(await apiGet(`/api/mujoco-validation/state?t=${Date.now()}`));
    } catch (error) {
      window.clearInterval(validationTimer);
      validationTimer = 0;
      validationRunning = false;
      showNotice(`无法读取仿真状态：${error.message}`, "error");
    }
  }

  async function startValidation() {
    if (
      pipeline.state !== "GRASP_PLANNING"
      || !["GRASP_READY", "PLANNING_REJECTED"].includes(graspPlanningState?.status)
      || graspPlanningState?.simulation_attempt?.available !== true
      || els.robotSelect.value !== "panda"
      || validationRunning
    ) return;
    validationRunning = true;
    els.startValidationButton.disabled = true;
    pipeline.transition("SCENE_SYNC", { transform: "NORMALIZED_VALIDATION_SCENE" });
    els.simulationState.textContent = "INITIALIZING";
    els.simulationFooter.textContent = "UNCALIBRATED · SIMULATION ONLY";
    try {
      const state = await apiPost("/api/mujoco-validation/start", {
        target_id: graspPlanningState.plan?.target_id
          || graspPlanningState.candidates?.[0]?.target_instance_id,
        scenario: els.validationScenarioSelect.value,
      });
      renderValidation(state);
      els.simulationMedia.src = `/api/mujoco-validation/live.mjpeg?opened=${Date.now()}`;
      simulationStreamStarted = true;
      els.simulationMedia.onload = () => {
        els.simulationMedia.hidden = false;
        els.simulationEmpty.hidden = true;
        els.simulationHud.hidden = false;
      };
      pipeline.transition("SIMULATION", { controller: "MUJOCO_POSITION_DLS_IK" });
      await pollValidationState();
      ensureValidationPolling();
    } catch (error) {
      validationRunning = false;
      els.simulationState.textContent = "FAILED";
      els.simulationFooter.textContent = "STATE ERROR";
      if (pipeline.state === "SCENE_SYNC") pipeline.transition("SIMULATION", { error: true });
      showNotice(`仿真验证无法启动：${error.message}`, "error");
      updateActionButtons();
    }
  }

  async function startGrasp() {
    if (!canStartGrasp(pipeline.state, targetPerceptionState)) return;
    const state = targetPerceptionState;
    const frame = state.frame;
    const target = state.selected_target;
    const snapshot = state.scene_snapshot;
    els.startGraspButton.disabled = true;
    try {
      els.spatialSnapshot.src = `/api/target-perception/scene-snapshot.jpg?revision=${state.revision}`;
    els.spatialSnapshot.hidden = false;
    els.spatialMediaLabels.hidden = true;
      els.spatialEmpty.hidden = true;
      els.spatialFooter.textContent = `FRAME ${frame.id} · ${target.id}`;
      els.statusSnapshot.textContent = `${frame.width} × ${frame.height} · Frame ${frame.id}`;
      pipeline.transition("SCENE_CAPTURED", {
        source: "phone-live-rgb",
        snapshotId: snapshot.snapshot_id,
        targetId: target.id,
        sourceFrameId: frame.id,
        sourceTimestampS: frame.timestamp_s,
      });
      pipeline.transition("SPATIAL_ANALYSIS", {
        module: "monocular-depth",
        snapshotId: snapshot.snapshot_id,
        targetId: target.id,
        sourceFrameId: frame.id,
      });
      await runSpatialAnalysis();
      if (pipeline.state === "SPATIAL_READY" && spatialPerceptionState?.observation) {
        await runGraspPlanning();
      }
    } catch (error) {
      updateActionButtons();
      showNotice(`无法开始空间分析：${error.message}`, "error");
    }
  }

  async function retrySpatialAnalysis() {
    if (pipeline.state !== "SPATIAL_ANALYSIS") return;
    await runSpatialAnalysis({ retry: true });
    if (pipeline.state === "SPATIAL_READY" && spatialPerceptionState?.observation) {
      await runGraspPlanning();
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
    spatialPerceptionState = null;
    spatialAnalysisRunning = false;
    els.spatialMediaLabels.hidden = true;
    els.targetOverlay.replaceChildren();
    setTargetOverlayVisible(false);
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
      els.targetLockValue.textContent = "离线产物 OFFLINE";
      els.targetDetail.textContent = "离线运行公开目标输出。";
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

  async function controlPlayback(action, extra = {}) {
    const state = await apiPost("/api/mujoco-validation/playback", { action, ...extra });
    renderValidation(state);
    if (!state.playback?.paused) ensureValidationPolling();
    return state;
  }

  function renderRecordingHistoryList(container, runs, saved) {
    container.replaceChildren();
    if (!runs.length) {
      const empty = document.createElement("p");
      empty.textContent = saved ? "暂无已保存 Recording。" : "当前会话暂无 Recording。";
      container.append(empty);
      return;
    }
    runs.forEach((run) => {
      const item = document.createElement("div");
      item.className = "recording-history-item";
      const title = document.createElement("strong");
      title.textContent = `${run.run_id || "Run"} · ${run.result?.state || "UNKNOWN"}`;
      const details = document.createElement("span");
      details.textContent = `${Number(run.duration_s || 0).toFixed(2)} s · ${saved ? "Saved" : (run.storage === "SAVED" ? "Saved" : "Unsaved")}`;
      const open = document.createElement("button");
      open.type = "button";
      open.textContent = "打开回放 Open";
      open.addEventListener("click", async () => {
        try {
          const state = await apiPost("/api/mujoco-validation/recording/open", {
            recording_id: run.recording_id,
            saved,
          });
          renderValidation(state);
          els.simulationMedia.src = `/api/mujoco-validation/live.mjpeg?recording=${encodeURIComponent(run.recording_id)}&opened=${Date.now()}`;
          els.simulationMedia.hidden = false;
          els.simulationEmpty.hidden = true;
          closeDialog(els.legacyDialog);
          pinView("simulation");
          showNotice(`已打开 ${saved ? "Saved Run" : "Session Recording"}，未重新执行原始 Pipeline。`);
        } catch (error) {
          showNotice(`无法打开 Recording：${error.message}`, "error");
        }
      });
      item.append(title, details, open);
      container.append(item);
    });
  }

  async function loadRecordingHistory() {
    const history = await apiGet(`/api/mujoco-validation/history?t=${Date.now()}`);
    renderRecordingHistoryList(
      els.sessionHistoryList,
      [...(history.session_history || []), ...(history.visualization_history || [])],
      false,
    );
    renderRecordingHistoryList(els.savedRunsList, history.saved_runs || [], true);
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
    const protocol = els.conditionSelect.value;
    showNotice(protocol === "NORMAL"
      ? "已选择正常条件 Normal：保持原始 RGB 像素完全不变。"
      : `已选择${CONDITION_LABELS[protocol] || protocol}：研究模式 Research Mode 将实时模拟可复现视觉退化。`, "success");
    restartLiveConditionPreview();
  });
  [els.stressStrategySelect, els.stressLevelSelect, els.stressBlurTypeSelect, els.stressSeedInput].forEach((control) => {
    control.addEventListener("change", () => {
      const settings = conditionExperimentSettings();
      showNotice(`压力测试参数已更新 Stress settings updated：${STRESS_LEVEL_LABELS[settings.level]} · 种子 Seed ${settings.random_seed}`);
      restartLiveConditionPreview();
    });
  });
  els.robotSelect.addEventListener("change", () => {
    const pending = els.robotSelect.value !== "panda";
    showNotice(pending ? "UR5e 接口已预留；本轮不执行多机器人仿真。" : "已选择 Franka Panda。", pending ? "error" : "success");
    updateActionButtons();
  });
  els.viewModeSelect.addEventListener("change", () => setViewMode(els.viewModeSelect.value));
  els.graspModeSelect.addEventListener("change", () => {
    const research = els.graspModeSelect.value === "RESEARCH";
    const label = research ? "研究模式 Research Mode" : "演示模式 Demo Mode";
    [els.stressStrategySelect, els.stressLevelSelect, els.stressBlurTypeSelect, els.stressSeedInput].forEach((control) => {
      control.disabled = !research;
    });
    showNotice(`抓取规划已切换为${label}；视觉压力测试仅在研究模式 Research Mode 生效。`);
    renderConditionReport(targetPerceptionState?.condition_report || null);
    restartLiveConditionPreview();
  });
  els.validationScenarioSelect.addEventListener("change", () => {
    const stress = els.validationScenarioSelect.value === "TARGET_OFFSET_STRESS";
    showNotice(stress
      ? "已选择 Target Offset Stress：只扰动物体位置，成功/失败仍由 MuJoCo 物理判定。"
      : "已选择 Nominal：执行当前真实 GraspPlan 的标称物理验证。", stress ? "error" : "success");
  });
  els.graspLayerControls.querySelectorAll("[data-grasp-layer]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      setGraspLayer(button.dataset.graspLayer);
    });
  });
  els.targetOverlay.addEventListener("pointerdown", selectTargetAtPointer);
  els.analyzeTargetsButton.addEventListener("click", analyzeTargets);
  els.startGraspButton.addEventListener("click", startGrasp);
  els.startValidationButton.addEventListener("click", startValidation);
  els.retrySpatialButton.addEventListener("click", retrySpatialAnalysis);
  els.newSceneButton.addEventListener("click", resumeLive);
  els.resumeLiveButton.addEventListener("click", resumeLive);
  els.resetPipelineButton.addEventListener("click", resetPipeline);
  document.querySelectorAll("[data-sim-camera]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      if (!validationState?.request && !validationState?.media?.replay_available) return;
      try {
        renderValidation(await apiPost("/api/mujoco-validation/camera-mode", { mode: button.dataset.simCamera }));
      } catch (error) {
        showNotice(`虚拟相机切换失败：${error.message}`, "error");
      }
    });
  });
  const simulationStage = els.simulationMedia.closest(".simulation-stage");
  let simulationPointer = null;
  simulationStage.addEventListener("pointerdown", (event) => {
    if ((!validationState?.request && !validationState?.media?.replay_available) || event.target.closest("button, input, label")) return;
    simulationPointer = { x: event.clientX, y: event.clientY, pan: event.shiftKey || event.button === 1 };
    simulationStage.setPointerCapture(event.pointerId);
    simulationStage.classList.add("is-dragging");
  });
  simulationStage.addEventListener("pointermove", (event) => {
    if (!simulationPointer || !simulationStage.hasPointerCapture(event.pointerId)) return;
    const dx = event.clientX - simulationPointer.x;
    const dy = event.clientY - simulationPointer.y;
    simulationPointer.x = event.clientX;
    simulationPointer.y = event.clientY;
    apiPost("/api/mujoco-validation/camera-manual", simulationPointer.pan
      ? { pan_x: -dx, pan_y: dy }
      : { rotate_x: -dx, rotate_y: dy }).then(renderValidation).catch(() => {});
  });
  function releaseSimulationPointer(event) {
    if (simulationStage.hasPointerCapture(event.pointerId)) simulationStage.releasePointerCapture(event.pointerId);
    simulationPointer = null;
    simulationStage.classList.remove("is-dragging");
  }
  simulationStage.addEventListener("pointerup", releaseSimulationPointer);
  simulationStage.addEventListener("pointercancel", releaseSimulationPointer);
  simulationStage.addEventListener("wheel", (event) => {
    if (!validationState?.request && !validationState?.media?.replay_available) return;
    event.preventDefault();
    apiPost("/api/mujoco-validation/camera-manual", { zoom: event.deltaY }).then(renderValidation).catch(() => {});
  }, { passive: false });
  document.querySelectorAll("[data-playback-action]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      try {
        await controlPlayback(button.dataset.playbackAction);
      } catch (error) {
        showNotice(`回放控制失败：${error.message}`, "error");
      }
    });
  });
  document.querySelectorAll("[data-playback-speed]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      try {
        await controlPlayback("SPEED", { speed: Number(button.dataset.playbackSpeed) });
      } catch (error) {
        showNotice(`播放速度切换失败：${error.message}`, "error");
      }
    });
  });
  els.playbackTimeline.addEventListener("input", (event) => {
    event.stopPropagation();
    const value = Number(els.playbackTimeline.value);
    els.playbackCurrentTime.textContent = value.toFixed(3);
    window.clearTimeout(playbackSeekTimer);
    playbackSeekTimer = window.setTimeout(() => {
      controlPlayback("SEEK", { time_s: value }).catch((error) => {
        showNotice(`时间轴定位失败：${error.message}`, "error");
      });
    }, 35);
  });
  els.technicalOverlayToggle.addEventListener("change", () => {
    controlPlayback("OVERLAY", { enabled: els.technicalOverlayToggle.checked }).catch((error) => {
      showNotice(`Technical Overlay 切换失败：${error.message}`, "error");
    });
  });
  els.saveRecordingButton.addEventListener("click", async (event) => {
    event.stopPropagation();
    els.saveRecordingButton.disabled = true;
    try {
      renderValidation(await apiPost("/api/mujoco-validation/recording/save"));
      showNotice("Recording 已保存到玄枢用户数据目录；未写入 Git 项目。", "success");
    } catch (error) {
      els.saveRecordingButton.disabled = false;
      showNotice(`保存 Recording 失败：${error.message}`, "error");
    }
  });
  els.exportVideoButton.addEventListener("click", async (event) => {
    event.stopPropagation();
    els.exportVideoButton.disabled = true;
    els.exportVideoButton.textContent = "正在导出 Exporting…";
    try {
      const exported = await apiPost("/api/mujoco-validation/export-video");
      showNotice(`视频已按当前镜头/速度/Overlay 导出：${exported.path}`, "success");
    } catch (error) {
      showNotice(`导出视频失败：${error.message}`, "error");
    } finally {
      els.exportVideoButton.disabled = false;
      els.exportVideoButton.textContent = "导出视频 Export Video";
    }
  });
  els.cameraSetupButton.addEventListener("click", () => openDialog(els.cameraSetupDialog));
  els.conditionSettingsButton.addEventListener("click", () => {
    openDialog(els.conditionDialog);
    renderConditionComparison();
  });
  document.querySelector("[data-close-condition]").addEventListener("click", () => closeDialog(els.conditionDialog));
  els.conditionDialog.addEventListener("click", (event) => {
    if (event.target === els.conditionDialog) closeDialog(els.conditionDialog);
  });
  els.conditionDialog.addEventListener("close", () => {
    [els.conditionRawPreview, els.conditionPipelinePreview].forEach((image) => {
      image.removeAttribute("src");
      image.hidden = true;
    });
  });
  document.querySelector("[data-close-camera-setup]").addEventListener("click", () => closeDialog(els.cameraSetupDialog));
  els.cameraSetupDialog.addEventListener("click", (event) => {
    if (event.target === els.cameraSetupDialog) closeDialog(els.cameraSetupDialog);
  });
  els.legacyButton.addEventListener("click", async () => {
    openDialog(els.legacyDialog);
    try { await loadRecordingHistory(); }
    catch (error) { showNotice(`无法读取 Recording History：${error.message}`, "error"); }
  });
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
    window.clearInterval(validationTimer);
    clearHistoricalUrls();
  });

  renderPipeline();
  setPrimaryView("live");
  (async function initializeWorkspace() {
    await restoreTargetPerceptionState();
    await restoreSpatialPerceptionState();
    await restoreGraspAndValidationState();
    await pollCameraState();
    cameraStateTimer = window.setInterval(pollCameraState, 1000);
  })();
})();
