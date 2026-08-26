(() => {
  "use strict";

  const SCHEMA_VERSION = "vision2grasp.run/v1";
  const PROCESS_STAGES = ["HOME", "PREGRASP", "DESCEND", "CLOSE", "LIFT"];
  const OUTCOME_STAGES = ["SUCCESS", "FAILURE"];
  const ALL_STAGES = [...PROCESS_STAGES, ...OUTCOME_STAGES];
  const VIEW_KEYS = ["rgb", "depth", "pointCloud", "mujoco"];
  const CONNECTED_STATES = new Set(["connected", "online", "ready", "running"]);
  const PUBLISHED_MANIFEST_URL = "../../runtime/latest.json";
  const PUBLISHED_SCHEMA_VERSION = "vision2grasp.launcher/v1";

  function emptySnapshot() {
    return {
      runId: null,
      timestamp: null,
      connection: "disconnected",
      stage: null,
      views: { rgb: null, depth: null, pointCloud: null, mujoco: null },
      target: null,
      candidates: [],
      selectedCandidateId: null,
      result: null,
      events: [],
    };
  }

  let state = emptySnapshot();
  let focusedView = null;
  let noticeTimer = null;
  let mediaObjectUrls = [];

  const els = {
    runId: document.querySelector("#runId"),
    runTimestamp: document.querySelector("#runTimestamp"),
    connectionBadge: document.querySelector("#connectionBadge"),
    snapshotInput: document.querySelector("#snapshotInput"),
    clearButton: document.querySelector("#clearButton"),
    contractButton: document.querySelector("#contractButton"),
    contractDialog: document.querySelector("#contractDialog"),
    visionWorkspace: document.querySelector("#visionWorkspace"),
    stageBadge: document.querySelector("#stageBadge"),
    targetPresence: document.querySelector("#targetPresence"),
    targetClass: document.querySelector("#targetClass"),
    targetConfidence: document.querySelector("#targetConfidence"),
    worldX: document.querySelector("#worldX"),
    worldY: document.querySelector("#worldY"),
    worldZ: document.querySelector("#worldZ"),
    rollValue: document.querySelector("#rollValue"),
    pitchValue: document.querySelector("#pitchValue"),
    yawValue: document.querySelector("#yawValue"),
    candidateCount: document.querySelector("#candidateCount"),
    candidateList: document.querySelector("#candidateList"),
    gripperWidth: document.querySelector("#gripperWidth"),
    candidateScore: document.querySelector("#candidateScore"),
    reachability: document.querySelector("#reachability"),
    resultCard: document.querySelector("#resultCard"),
    resultCode: document.querySelector("#resultCode"),
    resultText: document.querySelector("#resultText"),
    resultReason: document.querySelector("#resultReason"),
    eventCount: document.querySelector("#eventCount"),
    eventList: document.querySelector("#eventList"),
    flowStatus: document.querySelector("#flowStatus"),
    notice: document.querySelector("#notice"),
    rgbTargetBox: document.querySelector("#rgbTargetBox"),
  };

  const viewEls = {
    rgb: buildViewElements("rgb", "rgbSource"),
    depth: buildViewElements("depth", "depthSource"),
    pointCloud: buildViewElements("pointCloud", "pointCloudSource"),
    mujoco: buildViewElements("mujoco", "mujocoSource"),
  };

  function buildViewElements(key, sourceId) {
    const panel = document.querySelector(`[data-view="${key}"]`);
    return {
      panel,
      empty: panel.querySelector(".view-empty"),
      image: panel.querySelector(".view-image"),
      video: panel.querySelector(".view-video"),
      state: document.querySelector(`#${key}State`),
      source: document.querySelector(`#${sourceId}`),
      focus: panel.querySelector(".focus-button"),
    };
  }

  function isRecord(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function finiteNumber(value) {
    if (value === "" || value === null || value === undefined) return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function normalizedStage(value) {
    if (typeof value !== "string") return null;
    const stage = value.trim().toUpperCase();
    return ALL_STAGES.includes(stage) ? stage : null;
  }

  function safeMediaSource(value) {
    if (typeof value !== "string") return null;
    const source = value.trim();
    if (!source || /^javascript:/i.test(source)) return null;
    return source;
  }

  function normalizedView(value, key, resolveMediaPath) {
    if (!isRecord(value)) return null;
    const path = safeMediaSource(value.path);
    const src = path ? safeMediaSource(resolveMediaPath(path)) : null;
    if (!src) return null;
    const kind = value.kind === "video" ? "video" : "image";
    return {
      src,
      kind,
      label: typeof value.label === "string" && value.label.trim()
        ? value.label.trim()
        : `${key} · 真实数据已载入`,
    };
  }

  function normalizedCandidate(value, index) {
    if (!isRecord(value)) return null;
    const position = Array.isArray(value.position_world_m) ? value.position_world_m : [];
    const orientationValue = Array.isArray(value.orientation_world_rpy_deg) ? value.orientation_world_rpy_deg : [];
    return {
      id: String(value.candidate_id || `candidate-${index + 1}`),
      rank: finiteNumber(value.rank) ?? index + 1,
      score: finiteNumber(value.score),
      position: { x: position[0], y: position[1], z: position[2], unit: "m" },
      gripperWidth: finiteNumber(value.gripper_width_m),
      widthUnit: "m",
      orientation: {
        roll: orientationValue[0],
        pitch: orientationValue[1],
        yaw: orientationValue[2],
        unit: "deg",
      },
      reachable: value.reachable === true,
    };
  }

  function normalizedSnapshot(raw, resolveMediaPath = (path) => path) {
    if (!isRecord(raw)) throw new Error("快照根节点必须是 JSON 对象。");
    if (raw.schema_version !== SCHEMA_VERSION) {
      throw new Error(`仅支持 ${SCHEMA_VERSION}，当前为 ${String(raw.schema_version || "未声明版本")}。`);
    }

    const media = isRecord(raw.media) ? raw.media : {};
    const candidates = Array.isArray(raw.candidates)
      ? raw.candidates.map(normalizedCandidate).filter(Boolean)
      : [];
    candidates.sort((a, b) => {
      if (a.score === null && b.score === null) return a.rank - b.rank;
      if (a.score === null) return 1;
      if (b.score === null) return -1;
      return b.score - a.score;
    });

    const selectionValue = raw.selected_candidate_id;
    const requestedSelection = selectionValue === null || selectionValue === undefined
      ? null
      : String(selectionValue);
    const selectedCandidateId = candidates.some((candidate) => candidate.id === requestedSelection)
      ? requestedSelection
      : candidates[0]?.id || null;
    const execution = isRecord(raw.execution) ? raw.execution : null;
    const status = String(raw.status || "").toLowerCase();
    const resultStatus = execution
      ? (execution.success === true ? "success" : "failure")
      : (status === "success" || status === "failure" ? status : null);
    const result = resultStatus
      ? { status: resultStatus, reason: typeof execution?.message === "string" ? execution.message.trim() : "" }
      : null;
    const stage = normalizedStage(raw.stage);

    return {
      runId: raw.run_id,
      timestamp: raw.timestamp,
      connection: "connected",
      stage,
      views: {
        rgb: normalizedView(media.rgb, "RGB", resolveMediaPath),
        depth: normalizedView(media.depth, "Depth", resolveMediaPath),
        pointCloud: normalizedView(media.grasp_overlay, "Grasp Overlay", resolveMediaPath),
        mujoco: normalizedView(media.mujoco, "MuJoCo", resolveMediaPath),
      },
      target: isRecord(raw.target) ? raw.target : null,
      candidates,
      selectedCandidateId,
      result,
      events: Array.isArray(raw.events) ? raw.events.filter((item) => isRecord(item) || typeof item === "string") : [],
    };
  }

  function formatTimestamp(value) {
    if (value === null || value === undefined || value === "") return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(date);
  }

  function formatNumber(value, digits = 2) {
    const number = finiteNumber(value);
    return number === null ? "—" : number.toFixed(digits);
  }

  function millimeters(value, unit = "mm") {
    const number = finiteNumber(value);
    if (number === null) return "—";
    const normalizedUnit = String(unit || "mm").toLowerCase();
    const converted = normalizedUnit === "m" || normalizedUnit === "meter" || normalizedUnit === "meters"
      ? number * 1000
      : number;
    return converted.toFixed(2);
  }

  function degrees(value, unit = "deg") {
    const number = finiteNumber(value);
    if (number === null) return "—";
    const normalizedUnit = String(unit || "deg").toLowerCase();
    const converted = normalizedUnit === "rad" || normalizedUnit === "radian" || normalizedUnit === "radians"
      ? number * 180 / Math.PI
      : number;
    return `${converted.toFixed(1)}°`;
  }

  function formatConfidence(value) {
    const number = finiteNumber(value);
    if (number === null) return "—";
    const percentage = number <= 1 ? number * 100 : number;
    return `${percentage.toFixed(1)}%`;
  }

  function formatScore(value) {
    const number = finiteNumber(value);
    return number === null ? "—" : number.toFixed(3);
  }

  function selectedCandidate() {
    return state.candidates.find((candidate) => candidate.id === state.selectedCandidateId) || null;
  }

  function showNotice(message, type = "success") {
    window.clearTimeout(noticeTimer);
    els.notice.textContent = message;
    els.notice.className = `notice is-${type}`;
    els.notice.hidden = false;
    noticeTimer = window.setTimeout(() => {
      els.notice.hidden = true;
    }, 3200);
  }

  function renderHeader() {
    els.runId.textContent = state.runId === null || state.runId === "" ? "未载入" : String(state.runId);
    els.runTimestamp.textContent = formatTimestamp(state.timestamp);
    const connected = CONNECTED_STATES.has(state.connection);
    els.connectionBadge.classList.toggle("is-connected", connected);
    els.connectionBadge.classList.toggle("is-disconnected", !connected);
    els.connectionBadge.querySelector("span").textContent = connected ? "真实数据已连接" : "等待真实数据";
  }

  function resetMedia(view) {
    view.image.hidden = true;
    view.image.removeAttribute("src");
    view.video.pause();
    view.video.hidden = true;
    view.video.removeAttribute("src");
    view.video.load();
  }

  function renderView(key) {
    const view = viewEls[key];
    const source = state.views[key];
    resetMedia(view);
    view.state.classList.toggle("has-data", Boolean(source));
    view.state.textContent = source ? "REAL DATA" : "NO DATA";
    view.source.textContent = source?.label || "数据源未连接";
    view.empty.hidden = Boolean(source);
    if (!source) return;

    const media = source.kind === "video" ? view.video : view.image;
    media.hidden = false;
    media.src = source.src;
    media.addEventListener("error", () => {
      media.hidden = true;
      view.empty.hidden = false;
      view.state.classList.remove("has-data");
      view.state.textContent = "LOAD ERROR";
      view.source.textContent = "无法读取真实数据源";
    }, { once: true });
  }

  function normalizedBox(target) {
    if (!target) return null;
    const bbox = Array.isArray(target.bbox_xyxy) ? target.bbox_xyxy.map(finiteNumber) : [];
    const imageSize = isRecord(target.image_size_px) ? target.image_size_px : {};
    const imageWidth = finiteNumber(imageSize.width);
    const imageHeight = finiteNumber(imageSize.height);
    if (bbox.length !== 4 || bbox.some((value) => value === null) || !imageWidth || !imageHeight) return null;
    const [x1, y1, x2, y2] = bbox;
    if (x2 <= x1 || y2 <= y1) return null;
    return {
      x: Math.max(0, Math.min(1, x1 / imageWidth)),
      y: Math.max(0, Math.min(1, y1 / imageHeight)),
      width: Math.max(0, Math.min(1, (x2 - x1) / imageWidth)),
      height: Math.max(0, Math.min(1, (y2 - y1) / imageHeight)),
    };
  }

  function renderTargetBox() {
    const box = normalizedBox(state.target);
    const visible = Boolean(box && state.views.rgb);
    els.rgbTargetBox.hidden = !visible;
    if (!visible) return;
    els.rgbTargetBox.style.left = `${box.x * 100}%`;
    els.rgbTargetBox.style.top = `${box.y * 100}%`;
    els.rgbTargetBox.style.width = `${box.width * 100}%`;
    els.rgbTargetBox.style.height = `${box.height * 100}%`;
    els.rgbTargetBox.querySelector("span").textContent = state.target?.class_name || "TARGET";
  }

  function targetPosition(target) {
    const value = Array.isArray(target?.centroid_world_m) ? target.centroid_world_m : [];
    return value.length === 3 ? { x: value[0], y: value[1], z: value[2], unit: "m" } : null;
  }

  function renderTarget() {
    const target = state.target;
    const candidate = selectedCandidate();
    const position = targetPosition(target);
    const orientation = candidate?.orientation || null;
    const positionUnit = position?.unit || "m";
    const orientationUnit = orientation?.unit || "deg";

    els.targetPresence.textContent = target ? "TARGET LOCKED" : "NO TARGET";
    els.targetClass.textContent = target?.class_name ?? "—";
    els.targetConfidence.textContent = formatConfidence(target?.confidence);
    els.worldX.textContent = millimeters(position?.x, positionUnit);
    els.worldY.textContent = millimeters(position?.y, positionUnit);
    els.worldZ.textContent = millimeters(position?.z, positionUnit);
    els.rollValue.textContent = degrees(orientation?.roll, orientationUnit);
    els.pitchValue.textContent = degrees(orientation?.pitch, orientationUnit);
    els.yawValue.textContent = degrees(orientation?.yaw, orientationUnit);
  }

  function reachabilityText(candidate) {
    if (!candidate) return "—";
    return candidate.reachable ? "可达" : "不可达";
  }

  function renderCandidates() {
    els.candidateCount.textContent = String(state.candidates.length);
    els.candidateList.replaceChildren();

    if (!state.candidates.length) {
      const empty = document.createElement("div");
      empty.className = "empty-list";
      empty.textContent = "尚未收到真实抓取候选";
      els.candidateList.append(empty);
    } else {
      state.candidates.forEach((candidate, index) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "candidate-button";
        button.classList.toggle("is-selected", candidate.id === state.selectedCandidateId);
        button.setAttribute("aria-pressed", candidate.id === state.selectedCandidateId ? "true" : "false");
        const title = document.createElement("strong");
        title.textContent = `#${candidate.rank || index + 1}`;
        const summary = document.createElement("span");
        summary.textContent = `SCORE ${formatScore(candidate.score)}`;
        button.append(title, summary);
        button.addEventListener("click", () => {
          state.selectedCandidateId = candidate.id;
          renderCandidates();
          renderTarget();
        });
        els.candidateList.append(button);
      });
    }

    const candidate = selectedCandidate();
    els.gripperWidth.textContent = candidate
      ? millimeters(candidate.gripperWidth, candidate.widthUnit)
      : "—";
    els.candidateScore.textContent = formatScore(candidate?.score);
    els.reachability.textContent = reachabilityText(candidate);
  }

  function renderResult() {
    const result = state.result;
    els.resultCard.classList.remove("is-waiting", "is-success", "is-failure");
    if (!result) {
      els.resultCard.classList.add("is-waiting");
      els.resultCode.textContent = "WAITING";
      els.resultText.textContent = "等待真实执行结果";
      els.resultReason.textContent = "系统不会预设成功或失败。";
      return;
    }

    const success = result.status === "success";
    els.resultCard.classList.add(success ? "is-success" : "is-failure");
    els.resultCode.textContent = success ? "SUCCESS" : "FAILURE";
    els.resultText.textContent = success ? "动作序列完成" : "动作序列失败";
    els.resultReason.textContent = result.reason || (success ? "运行源未提供补充说明。" : "运行源未提供失败原因。");
  }

  function renderEvents() {
    els.eventCount.textContent = String(state.events.length);
    els.eventList.replaceChildren();
    if (!state.events.length) {
      const item = document.createElement("li");
      item.className = "empty-event";
      item.textContent = "暂无真实运行事件";
      els.eventList.append(item);
      return;
    }

    state.events.forEach((event) => {
      const item = document.createElement("li");
      if (typeof event === "string") {
        item.textContent = event;
      } else {
        const time = document.createElement("time");
        time.textContent = event.time || event.timestamp || "—";
        const message = document.createElement("span");
        message.textContent = event.message || event.text || event.stage || "未命名事件";
        item.append(time, message);
      }
      els.eventList.append(item);
    });
  }

  function renderFlow() {
    const stage = state.result?.status === "success"
      ? "SUCCESS"
      : state.result?.status === "failure"
        ? "FAILURE"
        : state.stage;
    const nodes = [...document.querySelectorAll(".flow-track li")];
    nodes.forEach((node) => node.classList.remove("is-done", "is-active"));
    els.stageBadge.classList.toggle("is-active", Boolean(stage));
    els.stageBadge.textContent = stage || "WAITING";

    if (!stage) {
      els.flowStatus.textContent = "等待真实状态";
      return;
    }

    const processIndex = PROCESS_STAGES.indexOf(stage);
    if (processIndex >= 0) {
      nodes.forEach((node) => {
        const index = PROCESS_STAGES.indexOf(node.dataset.stage);
        if (index >= 0 && index < processIndex) node.classList.add("is-done");
        if (node.dataset.stage === stage) node.classList.add("is-active");
      });
      els.flowStatus.textContent = `当前阶段 · ${stage}`;
      return;
    }

    PROCESS_STAGES.forEach((name) => {
      document.querySelector(`[data-stage="${name}"]`)?.classList.add("is-done");
    });
    document.querySelector(`[data-stage="${stage}"]`)?.classList.add("is-active");
    els.flowStatus.textContent = stage === "SUCCESS" ? "执行成功" : "执行失败";
  }

  function render() {
    renderHeader();
    VIEW_KEYS.forEach(renderView);
    renderTargetBox();
    renderCandidates();
    renderTarget();
    renderResult();
    renderEvents();
    renderFlow();
  }

  function toggleFocus(key) {
    focusedView = focusedView === key ? null : key;
    els.visionWorkspace.classList.toggle("has-focus", Boolean(focusedView));
    VIEW_KEYS.forEach((viewKey) => {
      const view = viewEls[viewKey];
      const active = focusedView === viewKey;
      view.panel.classList.toggle("is-focused", active);
      view.focus.setAttribute("aria-pressed", active ? "true" : "false");
      view.focus.setAttribute("aria-label", active ? `恢复 ${viewKey} 四视图布局` : `放大 ${viewKey} 视图`);
    });
  }

  function revokeMediaUrls(urls = mediaObjectUrls) {
    urls.forEach((url) => URL.revokeObjectURL(url));
    if (urls === mediaObjectUrls) mediaObjectUrls = [];
  }

  function normalizedRunPath(value) {
    const path = String(value || "").replace(/\\/g, "/").replace(/^\.\//, "");
    if (!path || path.startsWith("/") || path.split("/").includes("..")) {
      throw new Error(`媒体路径不安全：${String(value)}`);
    }
    return path;
  }

  async function importRunDirectory(fileList) {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    const runFiles = files.filter((file) => file.name.toLowerCase() === "run.json");
    if (runFiles.length !== 1) {
      showNotice(`无法载入：目录中需要且只能有一个 run.json，当前找到 ${runFiles.length} 个。`, "error");
      els.snapshotInput.value = "";
      return;
    }

    const runFile = runFiles[0];
    const runRelativePath = normalizedRunPath(runFile.webkitRelativePath || runFile.name);
    const runDirectory = runRelativePath.includes("/") ? runRelativePath.slice(0, runRelativePath.lastIndexOf("/")) : "";
    const filesByPath = new Map(files.map((file) => [normalizedRunPath(file.webkitRelativePath || file.name), file]));
    const nextUrls = [];

    try {
      const text = await runFile.text();
      const raw = JSON.parse(text);
      const nextState = normalizedSnapshot(raw, (path) => {
        const mediaPath = normalizedRunPath(path);
        const fullPath = runDirectory ? `${runDirectory}/${mediaPath}` : mediaPath;
        const mediaFile = filesByPath.get(fullPath);
        if (!mediaFile) throw new Error(`缺少媒体文件：${mediaPath}`);
        const url = URL.createObjectURL(mediaFile);
        nextUrls.push(url);
        return url;
      });
      const previousUrls = mediaObjectUrls;
      state = nextState;
      mediaObjectUrls = nextUrls;
      render();
      revokeMediaUrls(previousUrls);
      showNotice(`已载入真实运行目录：${raw.run_id}`, "success");
    } catch (error) {
      revokeMediaUrls(nextUrls);
      showNotice(`无法载入运行目录：${error.message}`, "error");
    } finally {
      els.snapshotInput.value = "";
    }
  }

  async function loadPublishedRun() {
    const manifestUrl = new URL(PUBLISHED_MANIFEST_URL, window.location.href);
    manifestUrl.searchParams.set("t", String(Date.now()));

    let response;
    try {
      response = await fetch(manifestUrl, { cache: "no-store" });
    } catch (error) {
      showNotice(`无法读取自动运行结果：${error.message}`, "error");
      return;
    }

    if (response.status === 404) return;
    if (!response.ok) {
      showNotice(`无法读取自动运行结果：HTTP ${response.status}`, "error");
      return;
    }

    try {
      const manifest = await response.json();
      if (!isRecord(manifest) || manifest.schema_version !== PUBLISHED_SCHEMA_VERSION) {
        throw new Error("启动器结果清单版本不受支持。");
      }

      const runPath = normalizedRunPath(manifest.run_json);
      if (!runPath.toLowerCase().endsWith("/run.json")) {
        throw new Error("启动器结果清单未指向 run.json。");
      }

      const runtimeBaseUrl = new URL("../../runtime/", window.location.href);
      const runUrl = new URL(runPath, runtimeBaseUrl);
      runUrl.searchParams.set("t", String(Date.now()));
      const runResponse = await fetch(runUrl, { cache: "no-store" });
      if (!runResponse.ok) throw new Error(`run.json 返回 HTTP ${runResponse.status}`);

      const raw = await runResponse.json();
      const nextState = normalizedSnapshot(raw, (path) => {
        const mediaPath = normalizedRunPath(path);
        return new URL(mediaPath, runUrl).href;
      });
      const previousUrls = mediaObjectUrls;
      state = nextState;
      mediaObjectUrls = [];
      render();
      revokeMediaUrls(previousUrls);
      showNotice(`已自动载入本次抓取结果：${raw.run_id}`, "success");
    } catch (error) {
      showNotice(`无法载入自动运行结果：${error.message}`, "error");
    }
  }

  function openContract() {
    if (typeof els.contractDialog.showModal === "function") {
      els.contractDialog.showModal();
    } else {
      els.contractDialog.setAttribute("open", "");
    }
  }

  function closeContract() {
    if (typeof els.contractDialog.close === "function") {
      els.contractDialog.close();
    } else {
      els.contractDialog.removeAttribute("open");
    }
  }

  els.snapshotInput.addEventListener("change", () => importRunDirectory(els.snapshotInput.files));
  els.clearButton.addEventListener("click", () => {
    state = emptySnapshot();
    render();
    revokeMediaUrls();
    showNotice("当前前端运行数据已清空。", "success");
  });
  els.contractButton.addEventListener("click", openContract);
  els.contractDialog.querySelectorAll("[data-close-dialog]").forEach((button) => {
    button.addEventListener("click", closeContract);
  });
  els.contractDialog.addEventListener("click", (event) => {
    if (event.target === els.contractDialog) closeContract();
  });
  document.querySelectorAll("[data-focus-view]").forEach((button) => {
    button.addEventListener("click", () => toggleFocus(button.dataset.focusView));
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && focusedView) toggleFocus(focusedView);
  });
  window.addEventListener("beforeunload", () => revokeMediaUrls());

  render();
  loadPublishedRun();
})();
