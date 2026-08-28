(() => {
  "use strict";

  const CAMERA_SCHEMA_VERSION = "vision2grasp.camera/v1";
  let activeMode = "real";
  let stateTimer = 0;
  let latestCaptureRevision = -1;
  let latestPairingRevision = -1;
  let liveStreamStarted = false;
  let cameraShouldStream = false;
  let noticeTimer = 0;

  const els = {
    realModeButton: document.querySelector("#realModeButton"),
    simulationModeButton: document.querySelector("#simulationModeButton"),
    realSceneControls: document.querySelector("#realSceneControls"),
    simulationControls: document.querySelector("#simulationControls"),
    cameraInputShell: document.querySelector("#cameraInputShell"),
    realSceneShell: document.querySelector("#realSceneShell"),
    simulationShell: document.querySelector("#simulationShell"),
    connectPhoneButton: document.querySelector("#connectPhoneButton"),
    pairingPanel: document.querySelector("#pairingPanel"),
    cameraLiveBadge: document.querySelector("#cameraLiveBadge"),
    cameraFrameState: document.querySelector("#cameraFrameState"),
    cameraLiveImage: document.querySelector("#cameraLiveImage"),
    cameraLiveEmpty: document.querySelector("#cameraLiveEmpty"),
    cameraResolution: document.querySelector("#cameraResolution"),
    cameraFps: document.querySelector("#cameraFps"),
    cameraLatency: document.querySelector("#cameraLatency"),
    cameraConnectionState: document.querySelector("#cameraConnectionState"),
    cameraDevice: document.querySelector("#cameraDevice"),
    cameraConnection: document.querySelector("#cameraConnection"),
    cameraMode: document.querySelector("#cameraMode"),
    cameraSideResolution: document.querySelector("#cameraSideResolution"),
    cameraSideFps: document.querySelector("#cameraSideFps"),
    cameraSideLatency: document.querySelector("#cameraSideLatency"),
    pairingState: document.querySelector("#pairingState"),
    pairingQr: document.querySelector("#pairingQr"),
    setupQr: document.querySelector("#setupQr"),
    cameraLanAddress: document.querySelector("#cameraLanAddress"),
    pairedDevice: document.querySelector("#pairedDevice"),
    certificateFingerprint: document.querySelector("#certificateFingerprint"),
    refreshPairingButton: document.querySelector("#refreshPairingButton"),
    captureStatus: document.querySelector("#captureStatus"),
    captureResolution: document.querySelector("#captureResolution"),
    captureImage: document.querySelector("#captureImage"),
    captureEmpty: document.querySelector("#captureEmpty"),
    saveCaptureButton: document.querySelector("#saveCaptureButton"),
    runSimulationButton: document.querySelector("#runSimulationButton"),
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
    noticeTimer = window.setTimeout(() => { els.notice.hidden = true; }, 4200);
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
    els.cameraInputShell.hidden = !real;
    els.realSceneShell.hidden = true;
    els.simulationShell.hidden = real;
    if (!real) window.vision2graspSimulationWorkbench?.loadPublishedRun();
  }

  function formatResolution(resolution) {
    return resolution ? `${resolution.width} × ${resolution.height}` : "—";
  }

  function formatMetric(value, suffix, digits = 1) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? `${number.toFixed(digits)}${suffix}` : "—";
  }

  function startLiveView() {
    if (liveStreamStarted) return;
    liveStreamStarted = true;
    els.cameraLiveImage.src = `/api/camera/live.mjpeg?opened=${Date.now()}`;
    els.cameraLiveImage.onload = () => {
      els.cameraLiveImage.hidden = false;
      els.cameraLiveEmpty.hidden = true;
    };
    els.cameraLiveImage.onerror = () => {
      liveStreamStarted = false;
      els.cameraLiveImage.hidden = true;
      els.cameraLiveEmpty.hidden = false;
      window.setTimeout(() => {
        if (activeMode === "real" && cameraShouldStream) startLiveView();
      }, 1200);
    };
  }

  function renderState(state) {
    const connection = state.connection || {};
    const pairing = state.pairing || {};
    const device = state.device || {};
    const service = state.service || {};
    const capture = state.capture || {};
    const live = connection.status === "LIVE";
    cameraShouldStream = live;
    const paired = device.paired === true;
    const resolution = formatResolution(connection.resolution);
    const fps = formatMetric(connection.fps, " FPS");
    const latency = formatMetric(connection.latency_ms, " ms");

    els.runId.textContent = live ? `CAM-${connection.frame_revision}` : "GONGSHU-CAMERA-v1";
    els.runTimestamp.textContent = new Intl.DateTimeFormat("zh-CN", {
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    }).format(new Date());
    els.connectionBadge.classList.toggle("is-connected", paired);
    els.connectionBadge.classList.toggle("is-disconnected", !paired);
    els.connectionBadge.querySelector("span").textContent = live ? "手机 RGB 实时输入" : paired ? "手机已配对" : "等待手机配对";

    els.cameraLiveBadge.textContent = live ? "● LAN LIVE" : connection.status || "WAITING";
    els.cameraLiveBadge.classList.toggle("is-live", live);
    els.cameraFrameState.textContent = live ? "RGB STREAMING" : "NO FRAME";
    els.cameraFrameState.classList.toggle("is-live", live);
    els.cameraResolution.textContent = resolution;
    els.cameraFps.textContent = fps;
    els.cameraLatency.textContent = latency;
    els.cameraConnectionState.textContent = connection.status || "WAITING";
    els.cameraConnectionState.classList.toggle("is-connected", paired);
    els.cameraDevice.textContent = device.name || "Phone Camera";
    els.cameraConnection.textContent = live ? "● LAN Connected" : paired ? "● Device paired" : "○ Waiting";
    els.cameraMode.textContent = connection.mode || "IDLE";
    els.cameraSideResolution.textContent = resolution;
    els.cameraSideFps.textContent = fps;
    els.cameraSideLatency.textContent = latency;
    els.pairingState.textContent = pairing.status || "WAITING";
    els.pairingState.classList.toggle("is-connected", paired);
    els.cameraLanAddress.textContent = service.lan_address || "—";
    els.pairedDevice.textContent = paired ? (device.name || "Phone Camera") : "Not paired";
    els.certificateFingerprint.textContent = service.certificate_fingerprint_sha256 || "—";

    if (!paired && pairing.revision !== latestPairingRevision) {
      latestPairingRevision = pairing.revision;
      els.pairingQr.src = `/api/camera/pairing-qr.png?revision=${pairing.revision}`;
    }

    if (live) {
      els.cameraLiveImage.hidden = false;
      els.cameraLiveEmpty.hidden = true;
      startLiveView();
    } else if (liveStreamStarted && ["DISCONNECTED", "PAIRED", "WAITING", "STOPPED"].includes(connection.status)) {
      liveStreamStarted = false;
      els.cameraLiveImage.removeAttribute("src");
      els.cameraLiveImage.hidden = true;
      els.cameraLiveEmpty.hidden = false;
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
      renderState(state);
    } catch (error) {
      els.cameraConnectionState.textContent = "OFFLINE";
      els.cameraConnection.textContent = `Camera Service 未连接：${error.message}`;
    }
  }

  els.realModeButton.addEventListener("click", () => setMode("real"));
  els.simulationModeButton.addEventListener("click", () => setMode("simulation"));
  els.connectPhoneButton.addEventListener("click", () => {
    els.pairingPanel?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    showNotice("请先完成一次 Local CA 设置，然后扫描配对二维码。", "success");
  });
  els.refreshPairingButton.addEventListener("click", async () => {
    els.refreshPairingButton.disabled = true;
    try {
      await apiPost("/api/camera/pairing/refresh");
      const nonce = Date.now();
      els.pairingQr.src = `/api/camera/pairing-qr.png?t=${nonce}`;
      els.setupQr.src = `/api/camera/setup-qr.png?t=${nonce}`;
      latestPairingRevision = -1;
      liveStreamStarted = false;
      els.cameraLiveImage.removeAttribute("src");
      els.cameraLiveImage.hidden = true;
      els.cameraLiveEmpty.hidden = false;
      showNotice("已生成新的五分钟一次性配对二维码。", "success");
      await pollCameraState();
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
      showNotice(`高清原图已保存：${result.path}`, "success");
      await pollCameraState();
    } catch (error) {
      showNotice(`保存失败：${error.message}`, "error");
    } finally {
      els.saveCaptureButton.disabled = false;
    }
  });
  els.runSimulationButton.addEventListener("click", async () => {
    els.runSimulationButton.disabled = true;
    els.runSimulationButton.textContent = "仿真运行中…";
    try {
      const result = await apiPost("/api/simulation/run");
      await window.vision2graspSimulationWorkbench?.loadPublishedRun();
      showNotice(`仿真完成：${result.run_id}`, "success");
    } catch (error) {
      showNotice(`仿真失败：${error.message}`, "error");
    } finally {
      els.runSimulationButton.disabled = false;
      els.runSimulationButton.textContent = "运行单瓶仿真";
    }
  });

  setMode("real");
  pollCameraState();
  stateTimer = window.setInterval(pollCameraState, 1000);
  window.addEventListener("beforeunload", () => window.clearInterval(stateTimer));
})();
