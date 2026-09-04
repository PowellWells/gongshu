(() => {
  "use strict";

  const token = decodeURIComponent(location.pathname.split("/").filter(Boolean).pop() || "");
  const sessionKey = `xuanshu-camera-session:${location.host}`;
  const els = {
    preview: document.querySelector("#cameraPreview"),
    empty: document.querySelector("#cameraEmpty"),
    secureBadge: document.querySelector("#secureBadge"),
    liveIndicator: document.querySelector("#liveIndicator"),
    liveMode: document.querySelector("#liveModeButton"),
    captureMode: document.querySelector("#captureModeButton"),
    startCamera: document.querySelector("#startCameraButton"),
    startLive: document.querySelector("#startLiveButton"),
    capture: document.querySelector("#captureButton"),
    stopCamera: document.querySelector("#stopCameraButton"),
    nativeCapture: document.querySelector("#nativeCaptureInput"),
    statusDot: document.querySelector("#statusDot"),
    statusText: document.querySelector("#statusText"),
    device: document.querySelector("#deviceValue"),
    resolution: document.querySelector("#resolutionValue"),
    fps: document.querySelector("#fpsValue"),
    latency: document.querySelector("#latencyValue"),
    notice: document.querySelector("#notice"),
  };

  let sessionId = sessionStorage.getItem(sessionKey) || "";
  let mediaStream = null;
  let peerConnection = null;
  let telemetryChannel = null;
  let pingTimer = 0;
  let stateTimer = 0;
  let latestLatency = null;
  let activeMode = "LIVE";
  let liveStarting = false;
  const pendingPings = new Map();

  function notice(message, error = false) {
    els.notice.textContent = message;
    els.notice.className = `notice${error ? " is-error" : ""}`;
    els.notice.hidden = false;
    window.setTimeout(() => { els.notice.hidden = true; }, 4200);
  }

  function setStatus(message, connected = false) {
    els.statusText.textContent = message;
    els.statusDot.classList.toggle("is-connected", connected);
  }

  async function request(path, options = {}) {
    const response = await fetch(path, { cache: "no-store", ...options });
    if (!response.ok) {
      const message = (await response.text()).trim() || `HTTP ${response.status}`;
      throw new Error(message);
    }
    return response;
  }

  async function establishSession() {
    if (sessionId) {
      try {
        await request(`/api/session/${encodeURIComponent(sessionId)}/state`);
        setStatus("● LOCAL CONNECTION · PAIRED", true);
        return;
      } catch {
        sessionStorage.removeItem(sessionKey);
        sessionId = "";
      }
    }
    const response = await request(`/api/pair/${encodeURIComponent(token)}/claim`, { method: "POST" });
    const document = await response.json();
    sessionId = String(document.session_id || "");
    if (!sessionId) throw new Error("本地服务没有返回 Camera Session");
    sessionStorage.setItem(sessionKey, sessionId);
    setStatus("● LOCAL CONNECTION · PAIRED", true);
  }

  async function ensureCamera() {
    if (mediaStream?.active) return mediaStream;
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      throw new Error("当前页面不是可信 HTTPS 环境，请先安装电脑提供的本地 CA 证书");
    }
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        facingMode: { ideal: "environment" },
        width: { ideal: 1920, min: 1280 },
        height: { ideal: 1080, min: 720 },
        frameRate: { ideal: 30, max: 30 },
      },
    });
    els.preview.srcObject = mediaStream;
    await els.preview.play();
    els.empty.hidden = true;
    els.startCamera.textContent = "CAMERA READY";
    els.startCamera.disabled = true;
    els.startLive.disabled = false;
    els.capture.disabled = false;
    els.stopCamera.disabled = false;
    const settings = mediaStream.getVideoTracks()[0]?.getSettings?.() || {};
    els.device.textContent = mediaStream.getVideoTracks()[0]?.label || "Phone Camera";
    els.resolution.textContent = settings.width && settings.height ? `${settings.width} × ${settings.height}` : "READY";
    setStatus("摄像头已授权，等待启动 LIVE", true);
    return mediaStream;
  }

  function waitForIceGathering(pc) {
    if (pc.iceGatheringState === "complete") return Promise.resolve();
    return new Promise((resolve) => {
      const listener = () => {
        if (pc.iceGatheringState === "complete") {
          pc.removeEventListener("icegatheringstatechange", listener);
          resolve();
        }
      };
      pc.addEventListener("icegatheringstatechange", listener);
    });
  }

  function startTelemetry(channel) {
    window.clearInterval(pingTimer);
    pingTimer = window.setInterval(() => {
      if (channel.readyState !== "open") return;
      const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      pendingPings.set(id, performance.now());
      channel.send(JSON.stringify({ type: "ping", id }));
      channel.send(JSON.stringify({
        type: "telemetry",
        latency_ms: latestLatency,
        mode: activeMode,
        device: mediaStream?.getVideoTracks()[0]?.label || "Phone Camera",
      }));
      for (const [key, started] of pendingPings) {
        if (performance.now() - started > 10000) pendingPings.delete(key);
      }
    }, 1000);
  }

  async function startLive() {
    if (liveStarting) return;
    liveStarting = true;
    els.startLive.disabled = true;
    try {
      await ensureCamera();
      if (!sessionId) await establishSession();
      if (peerConnection && ["connected", "connecting"].includes(peerConnection.connectionState)) return;
      peerConnection = new RTCPeerConnection({ iceServers: [] });
      mediaStream.getVideoTracks().forEach((track) => peerConnection.addTrack(track, mediaStream));
      for (const sender of peerConnection.getSenders()) {
        if (sender.track?.kind !== "video") continue;
        const parameters = sender.getParameters();
        parameters.encodings = parameters.encodings?.length ? parameters.encodings : [{}];
        parameters.encodings[0].maxBitrate = 8_000_000;
        parameters.encodings[0].maxFramerate = 30;
        sender.setParameters(parameters).catch(() => {});
      }
      telemetryChannel = peerConnection.createDataChannel("xuanshu-telemetry", { ordered: true });
      telemetryChannel.addEventListener("open", () => startTelemetry(telemetryChannel));
      telemetryChannel.addEventListener("message", (event) => {
        try {
          const document = JSON.parse(event.data);
          if (document.type !== "pong") return;
          const started = pendingPings.get(document.id);
          if (started === undefined) return;
          latestLatency = Math.max(0, (performance.now() - started) / 2);
          pendingPings.delete(document.id);
          els.latency.textContent = `${latestLatency.toFixed(1)} ms`;
        } catch {
          // Ignore non-telemetry messages.
        }
      });
      peerConnection.addEventListener("connectionstatechange", () => {
        const state = peerConnection?.connectionState || "closed";
        if (state === "connected") {
          els.liveIndicator.textContent = "● LIVE";
          els.liveIndicator.classList.add("is-live");
          els.startLive.textContent = "STOP LIVE";
          setStatus("● LAN LIVE · RGB STREAMING", true);
        } else if (["failed", "disconnected", "closed"].includes(state)) {
          els.liveIndicator.textContent = "STANDBY";
          els.liveIndicator.classList.remove("is-live");
          els.startLive.textContent = "START LIVE";
          if (mediaStream?.active) setStatus("摄像头已连接，LIVE 已停止", true);
        }
      });
      setStatus("正在建立局域网 WebRTC…", true);
      const offer = await peerConnection.createOffer();
      await peerConnection.setLocalDescription(offer);
      await waitForIceGathering(peerConnection);
      const response = await request(`/api/session/${encodeURIComponent(sessionId)}/offer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(peerConnection.localDescription),
      });
      const answer = await response.json();
      await peerConnection.setRemoteDescription(answer);
    } finally {
      liveStarting = false;
      els.startLive.disabled = !mediaStream?.active;
    }
  }

  async function stopLive() {
    window.clearInterval(pingTimer);
    pingTimer = 0;
    pendingPings.clear();
    telemetryChannel?.close();
    telemetryChannel = null;
    peerConnection?.close();
    peerConnection = null;
    els.liveIndicator.textContent = "STANDBY";
    els.liveIndicator.classList.remove("is-live");
    els.startLive.textContent = "START LIVE";
    els.startLive.disabled = !mediaStream?.active;
    if (sessionId) {
      request(`/api/session/${encodeURIComponent(sessionId)}/disconnect`, { method: "POST", keepalive: true }).catch(() => {});
    }
  }

  async function takeHighResolutionPhoto() {
    await ensureCamera();
    const track = mediaStream.getVideoTracks()[0];
    if (!("ImageCapture" in window)) {
      els.nativeCapture.click();
      return;
    }
    try {
      const imageCapture = new ImageCapture(track);
      const capabilities = await imageCapture.getPhotoCapabilities().catch(() => null);
      const photoSettings = {};
      if (capabilities?.imageWidth?.max) photoSettings.imageWidth = capabilities.imageWidth.max;
      if (capabilities?.imageHeight?.max) photoSettings.imageHeight = capabilities.imageHeight.max;
      const blob = await imageCapture.takePhoto(photoSettings);
      await uploadCapture(blob);
    } catch {
      notice("浏览器无法直接取得高清照片，已切换到系统拍照界面。", false);
      els.nativeCapture.click();
    }
  }

  async function uploadCapture(blob) {
    if (!sessionId) await establishSession();
    els.capture.disabled = true;
    els.capture.textContent = "UPLOADING…";
    try {
      const response = await request(`/api/session/${encodeURIComponent(sessionId)}/capture`, {
        method: "POST",
        headers: { "Content-Type": blob.type || "image/jpeg" },
        body: blob,
      });
      const document = await response.json();
      els.resolution.textContent = `${document.width} × ${document.height}`;
      setStatus("● LAN CAPTURE · RECEIVED BY PC", true);
      notice(`高清照片已传回电脑：${document.width} × ${document.height}`);
    } finally {
      els.capture.disabled = false;
      els.capture.textContent = "TAKE PHOTO";
    }
  }

  function setMode(mode) {
    activeMode = mode;
    const live = mode === "LIVE";
    els.liveMode.classList.toggle("is-active", live);
    els.captureMode.classList.toggle("is-active", !live);
    els.startLive.hidden = !live;
    els.capture.hidden = live;
  }

  async function stopCamera() {
    await stopLive();
    mediaStream?.getTracks().forEach((track) => track.stop());
    mediaStream = null;
    els.preview.srcObject = null;
    els.empty.hidden = false;
    els.startCamera.disabled = false;
    els.startCamera.textContent = "START CAMERA";
    els.startLive.disabled = true;
    els.capture.disabled = true;
    els.stopCamera.disabled = true;
    setStatus("Camera 已停止；本地配对仍然有效", true);
  }

  async function pollState() {
    if (!sessionId) return;
    try {
      const response = await request(`/api/session/${encodeURIComponent(sessionId)}/state`);
      const state = await response.json();
      const connection = state.connection || {};
      if (connection.resolution) {
        els.resolution.textContent = `${connection.resolution.width} × ${connection.resolution.height}`;
      }
      els.fps.textContent = Number.isFinite(connection.fps) && connection.fps > 0 ? `${connection.fps.toFixed(1)}` : "—";
      if (connection.latency_ms !== null && connection.latency_ms !== undefined) {
        els.latency.textContent = `${Number(connection.latency_ms).toFixed(1)} ms`;
      }
    } catch (error) {
      setStatus(`本地会话已断开：${error.message}`, false);
    }
  }

  els.startCamera.addEventListener("click", () => ensureCamera().catch((error) => notice(error.message, true)));
  els.startLive.addEventListener("click", () => {
    if (peerConnection && ["connected", "connecting"].includes(peerConnection.connectionState)) {
      stopLive().catch(() => {});
    } else {
      startLive().catch((error) => { notice(`LIVE 启动失败：${error.message}`, true); stopLive().catch(() => {}); });
    }
  });
  els.capture.addEventListener("click", () => takeHighResolutionPhoto().catch((error) => notice(`拍摄失败：${error.message}`, true)));
  els.stopCamera.addEventListener("click", () => stopCamera().catch(() => {}));
  els.liveMode.addEventListener("click", () => setMode("LIVE"));
  els.captureMode.addEventListener("click", () => setMode("CAPTURE"));
  els.nativeCapture.addEventListener("change", () => {
    const file = els.nativeCapture.files?.[0];
    if (file) uploadCapture(file).catch((error) => notice(`照片上传失败：${error.message}`, true));
    els.nativeCapture.value = "";
  });

  if (!window.isSecureContext) {
    els.secureBadge.textContent = "HTTPS REQUIRED";
    setStatus("请先安装电脑提供的本地 CA 证书", false);
  }
  establishSession()
    .then(() => {
      stateTimer = window.setInterval(pollState, 1000);
      pollState();
    })
    .catch((error) => setStatus(`配对失败：${error.message}`, false));
  window.addEventListener("beforeunload", () => {
    window.clearInterval(stateTimer);
    window.clearInterval(pingTimer);
    peerConnection?.close();
    mediaStream?.getTracks().forEach((track) => track.stop());
  });
})();
