(() => {
  "use strict";

  const REAL_SCHEMA_VERSION = "vision2grasp.real-scene/v1";
  const POLL_INTERVAL_MS = 650;
  let activeMode = "real";
  let latestSnapshot = null;
  let calibrationPoints = [];
  let collectingCalibration = false;
  let noticeTimer = null;

  const els = {
    realModeButton: document.querySelector("#realModeButton"),
    simulationModeButton: document.querySelector("#simulationModeButton"),
    realSceneControls: document.querySelector("#realSceneControls"),
    simulationControls: document.querySelector("#simulationControls"),
    realSceneShell: document.querySelector("#realSceneShell"),
    simulationShell: document.querySelector("#simulationShell"),
    usePcCameraButton: document.querySelector("#usePcCameraButton"),
    androidStreamUrl: document.querySelector("#androidStreamUrl"),
    connectAndroidButton: document.querySelector("#connectAndroidButton"),
    realImageInput: document.querySelector("#realImageInput"),
    tableWidthMm: document.querySelector("#tableWidthMm"),
    tableHeightMm: document.querySelector("#tableHeightMm"),
    startCalibrationButton: document.querySelector("#startCalibrationButton"),
    calibrationGuide: document.querySelector("#calibrationGuide"),
    runSimulationButton: document.querySelector("#runSimulationButton"),
    realLiveImage: document.querySelector("#realLiveImage"),
    realSpatialImage: document.querySelector("#realSpatialImage"),
    realGraspImage: document.querySelector("#realGraspImage"),
    calibrationMarkers: document.querySelector("#calibrationMarkers"),
    realLiveState: document.querySelector("#realLiveState"),
    realSpatialState: document.querySelector("#realSpatialState"),
    realGraspState: document.querySelector("#realGraspState"),
    realValidationState: document.querySelector("#realValidationState"),
    realSourceLabel: document.querySelector("#realSourceLabel"),
    calibrationStatus: document.querySelector("#calibrationStatus"),
    realCandidateSummary: document.querySelector("#realCandidateSummary"),
    realPhaseBadge: document.querySelector("#realPhaseBadge"),
    realStatusMessage: document.querySelector("#realStatusMessage"),
    realTargetClass: document.querySelector("#realTargetClass"),
    realConfidence: document.querySelector("#realConfidence"),
    realTableX: document.querySelector("#realTableX"),
    realTableY: document.querySelector("#realTableY"),
    realYaw: document.querySelector("#realYaw"),
    realWidth: document.querySelector("#realWidth"),
    realCandidateList: document.querySelector("#realCandidateList"),
    validationReachability: document.querySelector("#validationReachability"),
    validationCollision: document.querySelector("#validationCollision"),
    validationWidth: document.querySelector("#validationWidth"),
    validationLift: document.querySelector("#validationLift"),
    validationFinal: document.querySelector("#validationFinal"),
    runId: document.querySelector("#runId"),
    runTimestamp: document.querySelector("#runTimestamp"),
    connectionBadge: document.querySelector("#connectionBadge"),
    notice: document.querySelector("#notice"),
  };

  function showNotice(message, type = "success") {
    window.clearTimeout(noticeTimer);
    els.notice.textContent = message;
    els.notice.className = `notice is-${type}`;
    els.notice.hidden = false;
    noticeTimer = window.setTimeout(() => {
      els.notice.hidden = true;
    }, 3800);
  }

  async function apiPost(path, body) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    let document = null;
    try {
      document = await response.json();
    } catch {
      throw new Error(`本地服务返回 HTTP ${response.status}`);
    }
    if (!response.ok || document.status === "error") {
      throw new Error(document.message || `本地服务返回 HTTP ${response.status}`);
    }
    return document;
  }

  function setMode(mode) {
    activeMode = mode;
    const real = mode === "real";
    document.body.dataset.activeMode = mode;
    els.realModeButton.classList.toggle("is-active", real);
    els.simulationModeButton.classList.toggle("is-active", !real);
    els.realModeButton.setAttribute("aria-pressed", String(real));
    els.simulationModeButton.setAttribute("aria-pressed", String(!real));
    els.realSceneControls.hidden = !real;
    els.simulationControls.hidden = real;
    els.realSceneShell.hidden = !real;
    els.simulationShell.hidden = real;
    if (real) {
      if (latestSnapshot) renderSnapshot(latestSnapshot);
    } else {
      window.vision2graspSimulationWorkbench?.loadPublishedRun();
    }
  }

  function formatPercent(value) {
    if (value === null || value === undefined || value === "") return "—";
    const number = Number(value);
    return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : "—";
  }

  function formatMillimeters(value) {
    if (value === null || value === undefined || value === "") return "—";
    const number = Number(value);
    return Number.isFinite(number) ? `${(number * 1000).toFixed(1)} mm` : "—";
  }

  function formatDegrees(value) {
    if (value === null || value === undefined || value === "") return "—";
    const number = Number(value);
    return Number.isFinite(number) ? `${number.toFixed(1)}°` : "—";
  }

  function setImage(image, path, revision, available) {
    const empty = image.parentElement.querySelector(".real-empty");
    image.hidden = !available;
    empty.hidden = available;
    if (available) image.src = `${path}?revision=${encodeURIComponent(revision)}`;
    else image.removeAttribute("src");
  }

  function renderHeader(snapshot) {
    const frame = snapshot.frame;
    els.runId.textContent = frame ? `REAL-${frame.frame_id}` : "REAL SCENE";
    els.runTimestamp.textContent = snapshot.captured_at
      ? new Intl.DateTimeFormat("zh-CN", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false,
        }).format(new Date(snapshot.captured_at))
      : "—";
    const connected = Boolean(frame);
    els.connectionBadge.classList.toggle("is-connected", connected);
    els.connectionBadge.classList.toggle("is-disconnected", !connected);
    els.connectionBadge.querySelector("span").textContent = connected
      ? "真实输入已连接"
      : "等待真实输入";
  }

  function renderCandidates(snapshot) {
    const candidates = Array.isArray(snapshot.candidates) ? snapshot.candidates : [];
    els.realCandidateSummary.textContent = `${candidates.length} CANDIDATES`;
    els.realCandidateList.replaceChildren();
    if (!candidates.length) {
      const paragraph = document.createElement("p");
      paragraph.textContent = snapshot.calibration?.ready
        ? "等待 bottle 检测"
        : "等待标定和 bottle 检测";
      els.realCandidateList.append(paragraph);
      return;
    }
    candidates.forEach((candidate, index) => {
      const item = document.createElement("div");
      item.className = `real-candidate${index === 0 ? " is-selected" : ""}`;
      const rank = document.createElement("b");
      rank.textContent = `#${candidate.rank}`;
      const detail = document.createElement("span");
      detail.textContent = `${formatDegrees(candidate.yaw_deg)} · ${formatMillimeters(candidate.estimated_gripper_width_m)}`;
      const score = document.createElement("strong");
      score.textContent = Number(candidate.final_score).toFixed(3);
      item.append(rank, detail, score);
      els.realCandidateList.append(item);
    });
  }

  function renderValidation(validation) {
    const value = validation || {};
    els.validationReachability.textContent = value.reachability || "NOT RUN";
    els.validationCollision.textContent = value.collision || "NOT RUN";
    els.validationWidth.textContent = value.gripper_width || "NOT RUN";
    els.validationLift.textContent = value.lift_test || "NOT RUN";
    els.validationFinal.textContent = value.final_result || "NOT RUN";
    els.realValidationState.textContent = value.status || "NOT RUN";
  }

  function renderSnapshot(snapshot) {
    if (activeMode !== "real") return;
    renderHeader(snapshot);
    const hasFrame = Boolean(snapshot.frame);
    const calibrated = snapshot.calibration?.ready === true;
    const target = snapshot.target;
    const hasCandidates = Array.isArray(snapshot.candidates) && snapshot.candidates.length > 0;
    setImage(els.realLiveImage, "/api/real-scene/frame/live.jpg", snapshot.revision, hasFrame);
    setImage(els.realSpatialImage, "/api/real-scene/frame/spatial.jpg", snapshot.revision, hasFrame);
    setImage(els.realGraspImage, "/api/real-scene/frame/grasp.jpg", snapshot.revision, hasFrame);
    els.realLiveState.textContent = target ? "TARGET LOCKED" : hasFrame ? "LIVE" : "WAITING";
    els.realSpatialState.textContent = calibrated ? "MEASURED XY" : "UNCALIBRATED";
    els.realGraspState.textContent = hasCandidates ? "CANDIDATES READY" : "WAITING";
    els.realLiveState.classList.toggle("is-ready", hasFrame);
    els.realSpatialState.classList.toggle("is-ready", calibrated);
    els.realGraspState.classList.toggle("is-ready", hasCandidates);
    els.realSourceLabel.textContent = snapshot.source?.name || snapshot.source?.kind || "NO SOURCE";
    els.calibrationStatus.textContent = calibrated
      ? `${(snapshot.calibration.table_width_m * 1000).toFixed(0)} × ${(snapshot.calibration.table_height_m * 1000).toFixed(0)} mm`
      : "NOT READY";
    els.realPhaseBadge.textContent = snapshot.phase || "ACQUIRE";
    els.realStatusMessage.textContent = snapshot.message || "等待真实输入源";
    els.realTargetClass.textContent = target?.class_name || "—";
    els.realConfidence.textContent = formatPercent(target?.confidence);
    els.realTableX.textContent = formatMillimeters(target?.center_table_m?.[0]);
    els.realTableY.textContent = formatMillimeters(target?.center_table_m?.[1]);
    els.realYaw.textContent = formatDegrees(target?.principal_yaw_deg);
    els.realWidth.textContent = formatMillimeters(target?.estimated_width_m);
    renderCandidates(snapshot);
    renderValidation(snapshot.simulation_validation);
    if (!collectingCalibration) renderCalibrationMarkers(snapshot.calibration?.image_points_px || []);
  }

  function imageGeometry() {
    const image = els.realLiveImage;
    if (!image.naturalWidth || !image.naturalHeight) return null;
    const rect = image.getBoundingClientRect();
    const scale = Math.min(rect.width / image.naturalWidth, rect.height / image.naturalHeight);
    const contentWidth = image.naturalWidth * scale;
    const contentHeight = image.naturalHeight * scale;
    return {
      rect,
      scale,
      offsetX: (rect.width - contentWidth) / 2,
      offsetY: (rect.height - contentHeight) / 2,
    };
  }

  function renderCalibrationMarkers(points) {
    els.calibrationMarkers.replaceChildren();
    const geometry = imageGeometry();
    if (!geometry) return;
    points.forEach((point, index) => {
      const marker = document.createElement("span");
      marker.className = "calibration-marker";
      marker.textContent = String(index + 1);
      marker.style.left = `${geometry.offsetX + point[0] * geometry.scale}px`;
      marker.style.top = `${geometry.offsetY + point[1] * geometry.scale}px`;
      els.calibrationMarkers.append(marker);
    });
  }

  async function finishCalibration() {
    const width = Number(els.tableWidthMm.value);
    const height = Number(els.tableHeightMm.value);
    try {
      await apiPost("/api/real-scene/calibration", {
        image_points_px: calibrationPoints,
        table_width_mm: width,
        table_height_mm: height,
      });
      collectingCalibration = false;
      els.startCalibrationButton.textContent = "重新标定";
      els.calibrationGuide.textContent = "标定已保存；移动相机后必须重新标定";
      els.calibrationGuide.classList.remove("is-active");
      showNotice("桌面四点标定已保存，正在生成真实抓取候选。", "success");
    } catch (error) {
      collectingCalibration = false;
      els.calibrationGuide.textContent = `标定失败：${error.message}`;
      els.calibrationGuide.classList.remove("is-active");
      showNotice(`标定失败：${error.message}`, "error");
    }
  }

  async function pollRealScene() {
    try {
      const response = await fetch(`/api/real-scene/state?t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const snapshot = await response.json();
      if (snapshot.schema_version !== REAL_SCHEMA_VERSION) {
        throw new Error("真实场景接口版本不匹配");
      }
      latestSnapshot = snapshot;
      renderSnapshot(snapshot);
    } catch (error) {
      if (activeMode === "real") {
        els.realStatusMessage.textContent = `本地实时服务未连接：${error.message}`;
        els.realPhaseBadge.textContent = "OFFLINE";
      }
    }
  }

  els.realModeButton.addEventListener("click", () => setMode("real"));
  els.simulationModeButton.addEventListener("click", () => setMode("simulation"));

  els.usePcCameraButton.addEventListener("click", async () => {
    try {
      await apiPost("/api/real-scene/source", { kind: "camera", value: 0 });
      showNotice("已切换到电脑摄像头。", "success");
    } catch (error) {
      showNotice(`无法打开电脑摄像头：${error.message}`, "error");
    }
  });

  els.connectAndroidButton.addEventListener("click", async () => {
    const value = els.androidStreamUrl.value.trim();
    if (!value) {
      showNotice("请先输入 Android 摄像头视频流地址。", "error");
      return;
    }
    try {
      await apiPost("/api/real-scene/source", { kind: "url", value });
      showNotice("Android 视频流已连接。", "success");
    } catch (error) {
      showNotice(`Android 视频流连接失败：${error.message}`, "error");
    }
  });

  els.realImageInput.addEventListener("change", async () => {
    const file = els.realImageInput.files?.[0];
    if (!file) return;
    try {
      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.addEventListener("load", () => resolve(reader.result), { once: true });
        reader.addEventListener("error", () => reject(new Error("无法读取图片")), { once: true });
        reader.readAsDataURL(file);
      });
      await apiPost("/api/real-scene/source", { kind: "image", data_url: dataUrl });
      showNotice(`已载入照片：${file.name}`, "success");
    } catch (error) {
      showNotice(`照片载入失败：${error.message}`, "error");
    } finally {
      els.realImageInput.value = "";
    }
  });

  els.startCalibrationButton.addEventListener("click", () => {
    if (!latestSnapshot?.frame || !els.realLiveImage.naturalWidth) {
      showNotice("请先连接摄像头或载入照片。", "error");
      return;
    }
    const width = Number(els.tableWidthMm.value);
    const height = Number(els.tableHeightMm.value);
    if (!Number.isFinite(width) || !Number.isFinite(height) || width < 50 || height < 50) {
      showNotice("桌面区域宽高必须至少为 50 mm。", "error");
      return;
    }
    collectingCalibration = true;
    calibrationPoints = [];
    renderCalibrationMarkers(calibrationPoints);
    els.startCalibrationButton.textContent = "采集中…";
    els.calibrationGuide.textContent = "请点击 1/4：桌面坐标原点";
    els.calibrationGuide.classList.add("is-active");
  });

  els.realLiveImage.addEventListener("click", (event) => {
    if (!collectingCalibration) return;
    const geometry = imageGeometry();
    if (!geometry) return;
    const x = (event.clientX - geometry.rect.left - geometry.offsetX) / geometry.scale;
    const y = (event.clientY - geometry.rect.top - geometry.offsetY) / geometry.scale;
    if (x < 0 || y < 0 || x >= els.realLiveImage.naturalWidth || y >= els.realLiveImage.naturalHeight) {
      showNotice("请点击实际画面区域，不要点击黑边。", "error");
      return;
    }
    calibrationPoints.push([x, y]);
    renderCalibrationMarkers(calibrationPoints);
    const prompts = ["+X 方向角点", "+X +Y 对角点", "+Y 方向角点"];
    if (calibrationPoints.length < 4) {
      els.calibrationGuide.textContent = `请点击 ${calibrationPoints.length + 1}/4：${prompts[calibrationPoints.length - 1]}`;
    } else {
      els.calibrationGuide.textContent = "正在计算桌面坐标映射…";
      finishCalibration();
    }
  });

  els.runSimulationButton.addEventListener("click", async () => {
    els.runSimulationButton.disabled = true;
    els.runSimulationButton.textContent = "仿真运行中…";
    try {
      const result = await apiPost("/api/simulation/run", {});
      await window.vision2graspSimulationWorkbench?.loadPublishedRun();
      showNotice(`仿真完成：${result.run_id} · Lift ${result.isolated_lift_acceptance}`, "success");
    } catch (error) {
      showNotice(`仿真失败：${error.message}`, "error");
    } finally {
      els.runSimulationButton.disabled = false;
      els.runSimulationButton.textContent = "运行单瓶仿真";
    }
  });

  window.addEventListener("resize", () => {
    if (collectingCalibration) renderCalibrationMarkers(calibrationPoints);
    else if (latestSnapshot) renderCalibrationMarkers(latestSnapshot.calibration?.image_points_px || []);
  });

  setMode("real");
  pollRealScene();
  const pollTimer = window.setInterval(pollRealScene, POLL_INTERVAL_MS);
  window.addEventListener("beforeunload", () => window.clearInterval(pollTimer));
})();
