(() => {
  "use strict";

  const BACKEND_API = "/api";
  const MAX_FILE_SIZE = 50 * 1024 * 1024;
  const HANDOFF_DB = "hotarea-cv-moment";
  const HANDOFF_STORE = "handoff";
  const HANDOFF_KEY = "latest";
  const rules = window.JingweiMomentRules;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  const state = {
    file: null,
    imageUrl: null,
    payload: null,
    items: [],
    selectedId: null,
    filter: "all",
    running: false,
    handingOff: false,
    startedAt: 0,
    summary: null,
    timelineProgress: 0,
    ghostMode: false,
    ghostActivations: 0,
    hoveredId: null,
    completionTimer: null,
    timelineDragging: false,
    selectionTimer: null,
    signalTimer: null,
    locationTimer: null,
    evidenceTimer: null,
    retainTimer: null,
    completingTimer: null,
    replaying: false,
    evidenceConvergencePlayed: false,
    magnetPointer: null,
    magnetStrength: 0,
    magnetReleaseStarted: 0,
    magnetFrame: 0,
  };

  const els = {
    landingView: document.querySelector("#landingView"),
    analysisView: document.querySelector("#analysisView"),
    dropZone: document.querySelector("#dropZone"),
    imageInput: document.querySelector("#imageInput"),
    chooseButton: document.querySelector("#chooseButton"),
    sampleButton: document.querySelector("#sampleButton"),
    newImageButton: document.querySelector("#newImageButton"),
    replayButton: document.querySelector("#replayButton"),
    reviewButtons: [document.querySelector("#reviewButton"), document.querySelector("#reviewButtonTop")],
    runtimeBadge: document.querySelector("#runtimeBadge"),
    analysisTitle: document.querySelector("#analysisTitle"),
    elapsedTime: document.querySelector("#elapsedTime"),
    pipelineList: document.querySelector("#pipelineList"),
    pipelineNote: document.querySelector("#pipelineNote"),
    imageName: document.querySelector("#imageName"),
    imageMeta: document.querySelector("#imageMeta"),
    imagePanel: document.querySelector(".image-panel"),
    analysisGrid: document.querySelector(".analysis-grid"),
    imageStage: document.querySelector("#imageStage"),
    fieldMagnet: document.querySelector("#fieldMagnet"),
    imageSurface: document.querySelector("#imageSurface"),
    sourceImage: document.querySelector("#sourceImage"),
    overlay: document.querySelector("#momentOverlay"),
    scanIndicator: document.querySelector("#scanIndicator"),
    scanMode: document.querySelector("#scanMode"),
    scanLayer: document.querySelector("#scanLayer"),
    analysisMatrix: document.querySelector("#analysisMatrix"),
    matrixInitial: document.querySelector("#matrixInitial"),
    matrixRejected: document.querySelector("#matrixRejected"),
    matrixRetained: document.querySelector("#matrixRetained"),
    matrixRate: document.querySelector("#matrixRate"),
    visionStatus: document.querySelector("#visionStatus"),
    statusVision: document.querySelector("#statusVision"),
    statusCandidates: document.querySelector("#statusCandidates"),
    statusTime: document.querySelector("#statusTime"),
    statusState: document.querySelector("#statusState"),
    signalCloud: document.querySelector("#signalCloud"),
    ghostModeBadge: document.querySelector("#ghostModeBadge"),
    probe: document.querySelector("#probe"),
    coordinateReadout: document.querySelector("#coordinateReadout"),
    coordinateFieldSize: document.querySelector("#coordinateFieldSize"),
    coordinateX: document.querySelector("#coordinateX"),
    coordinateY: document.querySelector("#coordinateY"),
    coordinateBox: document.querySelector("#coordinateBox"),
    lockFlash: document.querySelector("#lockFlash"),
    lens: document.querySelector("#jingweiLens"),
    lensCoordinate: document.querySelector("#lensCoordinate"),
    lensType: document.querySelector("#lensType"),
    lensBbox: document.querySelector("#lensBbox"),
    lensConfidence: document.querySelector("#lensConfidence"),
    lensWhy: document.querySelector("#lensWhy"),
    timeMachine: document.querySelector("#timeMachine"),
    timelineRange: document.querySelector("#timelineRange"),
    timelineControl: document.querySelector(".timeline-control"),
    timelineState: document.querySelector("#timelineState"),
    timelineEventTitle: document.querySelector("#timelineEventTitle"),
    timelineEventCopy: document.querySelector("#timelineEventCopy"),
    evidenceDock: document.querySelector("#evidenceDock"),
    momentComplete: document.querySelector("#momentComplete"),
    momentCompleteCount: document.querySelector("#momentCompleteCount"),
    resultFilters: document.querySelector("#resultFilters"),
    explainEmpty: document.querySelector("#explainEmpty"),
    explainContent: document.querySelector("#explainContent"),
    decisionBadge: document.querySelector("#decisionBadge"),
    explainPanel: document.querySelector("#explainPanel"),
    candidateId: document.querySelector("#candidateId"),
    candidateType: document.querySelector("#candidateType"),
    candidateDecision: document.querySelector("#candidateDecision"),
    candidateConfidence: document.querySelector("#candidateConfidence"),
    confidenceMeter: document.querySelector("#confidenceMeter"),
    candidateWhy: document.querySelector("#candidateWhy"),
    candidateSuggestion: document.querySelector("#candidateSuggestion"),
    reasonTags: document.querySelector("#reasonTags"),
    bboxValue: document.querySelector("#bboxValue"),
    reasonCoreResult: document.querySelector("#reasonCoreResult"),
    analysisSignal: document.querySelector("#analysisSignal"),
    evidenceConvergence: document.querySelector("#evidenceConvergence"),
    summaryPanel: document.querySelector("#summaryPanel"),
    summaryText: document.querySelector("#summaryText"),
    pageStateText: document.querySelector("#pageStateText"),
    counts: {
      all: document.querySelector("#allCount"),
      keep: document.querySelector("#keepCount"),
      pending: document.querySelector("#pendingCount"),
      ignored: document.querySelector("#ignoredCount"),
      summaryKeep: document.querySelector("#summaryKeep"),
      summaryPending: document.querySelector("#summaryPending"),
      summaryIgnored: document.querySelector("#summaryIgnored"),
    },
  };

  function pipelineItem(stage) {
    return els.pipelineList.querySelector(`[data-stage="${stage}"]`);
  }

  function resetPipeline() {
    els.pipelineList.querySelectorAll("li").forEach((item) => {
      item.classList.remove("is-active", "is-done");
      item.querySelector("span").textContent = item.dataset.stage === "candidates" || item.dataset.stage === "filter" || item.dataset.stage === "final"
        ? "等待真实结果"
        : "等待开始";
    });
  }

  function activateStage(stage, text) {
    els.pipelineList.querySelectorAll("li").forEach((item) => item.classList.remove("is-active"));
    const item = pipelineItem(stage);
    item.classList.add("is-active");
    item.querySelector("span").textContent = text;
  }

  function completeStage(stage, text) {
    const item = pipelineItem(stage);
    item.classList.remove("is-active");
    item.classList.add("is-done");
    item.querySelector("span").textContent = text;
  }

  function setScan(text, visible = true, mode = "SCAN · ACTIVE") {
    els.scanIndicator.querySelector("span").textContent = text;
    els.scanMode.textContent = mode;
    els.scanIndicator.classList.toggle("is-hidden", !visible);
  }

  function sleep(milliseconds) {
    return new Promise((resolve) => setTimeout(resolve, reduceMotion.matches ? 0 : milliseconds));
  }

  function clamp(value, minimum = 0, maximum = 1) {
    return Math.min(maximum, Math.max(minimum, value));
  }

  function scheduleMagneticField() {
    if (state.magnetFrame) return;
    state.magnetFrame = window.requestAnimationFrame((timestamp) => {
      state.magnetFrame = 0;
      drawMagneticField(timestamp);
    });
  }

  function drawMagneticField(timestamp = performance.now()) {
    const canvas = els.fieldMagnet;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;
    const pixelRatio = Math.min(2, window.devicePixelRatio || 1);
    const targetWidth = Math.round(width * pixelRatio);
    const targetHeight = Math.round(height * pixelRatio);
    if (canvas.width !== targetWidth || canvas.height !== targetHeight) {
      canvas.width = targetWidth;
      canvas.height = targetHeight;
    }
    const context = canvas.getContext("2d");
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    context.clearRect(0, 0, width, height);

    if (state.magnetReleaseStarted && state.magnetPointer) {
      const releaseProgress = clamp((timestamp - state.magnetReleaseStarted) / 760);
      state.magnetStrength = Math.pow(1 - releaseProgress, 3);
      if (releaseProgress < 1) {
        scheduleMagneticField();
      } else {
        state.magnetPointer = null;
        state.magnetReleaseStarted = 0;
        state.magnetStrength = 0;
      }
    }

    const spacing = 28;
    const radius = 64;
    const pointer = state.magnetPointer;
    const glowStrength = pointer ? state.magnetStrength : 0;
    if (pointer && glowStrength > .001) {
      const glowRadius = 96;
      const glow = context.createRadialGradient(pointer.x, pointer.y, 0, pointer.x, pointer.y, glowRadius);
      glow.addColorStop(0, `rgba(31,122,255,${.16 * glowStrength})`);
      glow.addColorStop(.38, `rgba(56,189,248,${.08 * glowStrength})`);
      glow.addColorStop(1, "rgba(109,196,255,0)");
      context.fillStyle = glow;
      context.fillRect(pointer.x - glowRadius, pointer.y - glowRadius, glowRadius * 2, glowRadius * 2);
    }
    let maximumOffset = 0;
    for (let y = 0; y <= height + spacing; y += spacing) {
      for (let x = 0; x <= width + spacing; x += spacing) {
        let drawX = x;
        let drawY = y;
        let influence = 0;
        if (pointer) {
          const deltaX = pointer.x - x;
          const deltaY = pointer.y - y;
          const distance = Math.hypot(deltaX, deltaY);
          if (distance < radius) {
            influence = (1 - distance / radius) * state.magnetStrength;
            const offset = reduceMotion.matches ? 0 : 2 * influence;
            if (distance > .01) {
              drawX += deltaX / distance * offset;
              drawY += deltaY / distance * offset;
            }
            maximumOffset = Math.max(maximumOffset, offset);
          }
        }
        context.beginPath();
        context.arc(drawX, drawY, 1 + influence * .3, 0, Math.PI * 2);
        context.fillStyle = `rgba(38,103,181,${.18 + influence * .1})`;
        context.fill();
      }
    }
    canvas.dataset.magnetActive = pointer && state.magnetStrength > .001 ? "true" : "false";
    canvas.dataset.magnetStrength = state.magnetStrength.toFixed(3);
    canvas.dataset.maxOffset = maximumOffset.toFixed(2);
    canvas.dataset.glowOpacity = (.16 * glowStrength).toFixed(3);
  }

  function updateMagneticField(event) {
    const rect = els.imageStage.getBoundingClientRect();
    state.magnetPointer = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    state.magnetStrength = 1;
    state.magnetReleaseStarted = 0;
    scheduleMagneticField();
  }

  function releaseMagneticField() {
    if (!state.magnetPointer) return;
    if (reduceMotion.matches) {
      state.magnetPointer = null;
      state.magnetStrength = 0;
      state.magnetReleaseStarted = 0;
    } else {
      state.magnetReleaseStarted = performance.now();
    }
    scheduleMagneticField();
  }

  function releaseMagneticFieldIfOutside(event) {
    if (!state.magnetPointer || state.magnetReleaseStarted) return;
    const rect = els.imageStage.getBoundingClientRect();
    const outside = event.clientX < rect.left || event.clientX > rect.right
      || event.clientY < rect.top || event.clientY > rect.bottom;
    if (outside) releaseMagneticField();
  }

  function timelineStage(progress) {
    if (progress < 0.125) return { label: "00.00s · IMAGE", status: "IMAGE", title: "IMAGE LOCKED", copy: "Source image anchored to the vision field" };
    if (progress < 0.422) return { label: "00.48s · STRUCTURE", status: "STRUCTURE", title: "STRUCTURE PARSED", copy: "Interface geometry and visual hierarchy observed" };
    if (progress < 0.654) return { label: "01.62s · SIGNALS", status: "SIGNALS", title: "SIGNALS FOUND", copy: "{initial} initial candidates discovered" };
    if (progress < 0.999) return { label: "02.51s · FILTER", status: "FILTERING", title: "FILTERING", copy: "{rejected} invalid or duplicated regions rejected" };
    return { label: "03.84s · RETAIN", status: "COMPLETE", title: "RETAIN", copy: "{final} actionable regions remain" };
  }

  function syncPipelineToTimeline(progress) {
    const stages = [...els.pipelineList.querySelectorAll("li")];
    const currentIndex = progress < .125 ? 0 : progress < .422 ? 1 : progress < .654 ? 2 : progress < .999 ? 3 : 4;
    stages.forEach((item, index) => {
      item.classList.toggle("is-done", progress >= .999 || index < currentIndex);
      item.classList.toggle("is-active", progress < .999 && index === currentIndex);
    });
  }

  function resetCandidateExplanation() {
    window.clearTimeout(state.selectionTimer);
    state.selectedId = null;
    els.explainEmpty.hidden = false;
    els.explainContent.hidden = true;
    els.decisionBadge.textContent = state.summary ? "等待选择" : "等待结果";
    els.explainPanel.classList.remove("is-linked", "is-awakening");
    els.overlay.querySelector(".selection-guides")?.remove();
    updateOverlayVisibility();
  }

  function pulseRetainedCandidates() {
    window.clearTimeout(state.retainTimer);
    els.overlay.classList.remove("is-retain-pulse");
    void els.overlay.getBoundingClientRect();
    els.overlay.classList.add("is-retain-pulse");
    state.retainTimer = window.setTimeout(() => els.overlay.classList.remove("is-retain-pulse"), reduceMotion.matches ? 20 : 620);
  }

  function renderSignalCloud(initialCount) {
    els.signalCloud.replaceChildren();
    const dotCount = Math.max(28, Math.min(120, Math.round(Math.sqrt(Math.max(1, initialCount)) * 11)));
    for (let index = 0; index < dotCount; index += 1) {
      const signal = document.createElement("i");
      const x = (index * 47 + index * index * 13) % 97;
      const y = (index * 71 + index * index * 7) % 94;
      signal.style.setProperty("--signal-x", `${x}%`);
      signal.style.setProperty("--signal-y", `${y}%`);
      signal.style.setProperty("--signal-size", `${2 + index % 4}px`);
      signal.style.setProperty("--signal-radius", index % 4 === 0 ? "50%" : "1px");
      signal.style.setProperty("--signal-opacity", String(.24 + (index % 7) * .08));
      signal.style.setProperty("--signal-rotate", `${(index * 29) % 180}deg`);
      signal.style.setProperty("--signal-delay", `${(index % 20) * 18}ms`);
      els.signalCloud.append(signal);
    }
  }

  function applyTimelineProgress(rawValue) {
    const value = clamp(Number(rawValue) / 1000);
    const previousValue = state.timelineProgress;
    state.timelineProgress = value;
    els.timelineRange.value = String(Math.round(value * 1000));
    els.timeMachine.style.setProperty("--timeline-progress", `${value * 100}%`);
    const stage = timelineStage(value);
    els.timelineState.textContent = stage.label;
    els.timelineEventTitle.textContent = stage.title;
    const currentPoint = value < .125 ? 0 : value < .422 ? 125 : value < .654 ? 422 : value < .999 ? 654 : 1000;
    els.timeMachine.querySelectorAll("[data-timeline]").forEach((button) => {
      button.classList.toggle("is-active", Number(button.dataset.timeline) <= value * 1000 + 1);
      button.classList.toggle("is-current", Number(button.dataset.timeline) === currentPoint);
    });

    if (!state.summary) {
      return;
    }
    const summary = state.summary;
    const rejected = Math.max(0, summary.initial - summary.final);
    els.timelineEventCopy.textContent = stage.copy
      .replace("{initial}", summary.initial.toLocaleString("en-US"))
      .replace("{rejected}", rejected.toLocaleString("en-US"))
      .replace("{final}", summary.final.toLocaleString("en-US"));
    const initialProgress = clamp((value - .125) / (.422 - .125));
    const filterProgress = clamp((value - .422) / (.654 - .422));
    const retainProgress = clamp((value - .654) / (1 - .654));
    const initialValue = Math.round(summary.initial * initialProgress);
    const rejectedValue = Math.round(rejected * filterProgress);
    const retainedValue = Math.round(summary.final * retainProgress);
    const filterRate = summary.initial > 0 ? rejectedValue / summary.initial * 100 : 0;
    els.matrixInitial.textContent = initialValue.toLocaleString("en-US");
    els.matrixRejected.textContent = rejectedValue.toLocaleString("en-US");
    els.matrixRetained.textContent = retainedValue.toLocaleString("en-US");
    els.matrixRate.textContent = `${filterRate.toFixed(1)}%`;
    els.statusCandidates.textContent = String(retainedValue);
    els.statusState.textContent = stage.status;
    els.imageStage.classList.toggle("is-scanning", state.replaying && value >= .125 && value < .422);
    els.imageStage.classList.toggle("is-structure", value >= .125 && value < .422);
    els.signalCloud.style.opacity = String(value < .125 || value >= .654 ? 0 : value < .422 ? initialProgress : Math.max(.08, 1 - filterProgress));
    els.signalCloud.classList.toggle("is-filtering", value >= .422 && value < .654);
    syncPipelineToTimeline(value);
    if (value < .999 && state.selectedId) resetCandidateExplanation();
    if (previousValue < .999 && value >= .999) pulseRetainedCandidates();

    const groups = [...els.overlay.querySelectorAll(".moment-box")];
    const ignoredGroups = groups.filter((group) => group.classList.contains("ignored"));
    const finalGroups = groups.filter((group) => !group.classList.contains("ignored"));
    groups.forEach((group, index) => {
      group.classList.add("is-timeline-controlled");
      const candidate = state.items.find((item) => item.moment_id === group.dataset.momentId);
      const filteredOut = state.filter !== "all" && candidate?.decision !== state.filter;
      let opacity = 0;
      let scale = .96;
      if (value >= .2 && value < .422) {
        const entrance = clamp((value - (.2 + index / Math.max(1, groups.length) * .15)) / .07);
        opacity = entrance * .82;
        scale = .97 + entrance * .03;
      } else if (value >= .422 && value < .654) {
        if (candidate?.decision === "ignored") {
          const ignoredIndex = ignoredGroups.indexOf(group);
          const fade = clamp((filterProgress - ignoredIndex / Math.max(1, ignoredGroups.length) * .68) / .25);
          opacity = .82 * (1 - fade);
          scale = 1 - fade * .12;
        } else {
          opacity = .82 - filterProgress * .58;
          scale = 1;
        }
      } else if (value >= .654) {
        if (candidate?.decision !== "ignored") {
          const finalIndex = finalGroups.indexOf(group);
          const locked = clamp((retainProgress - finalIndex / Math.max(1, finalGroups.length) * .76) / .22);
          opacity = .24 + locked * .76;
          scale = .96 + locked * .04;
        }
      }
      const showGhost = state.ghostMode && candidate?.decision === "ignored";
      const showIgnoredFilter = state.filter === "ignored" && candidate?.decision === "ignored";
      if (showGhost || showIgnoredFilter) {
        opacity = .82;
        scale = 1;
      }
      group.style.opacity = filteredOut && !showGhost ? "0" : String(opacity);
      group.style.transform = `scale(${scale})`;
      group.style.transformOrigin = "center";
      group.style.pointerEvents = opacity > .08 && (!filteredOut || showGhost) ? "auto" : "none";
    });
    if (state.replaying && previousValue < .422 && value >= .422 && !state.evidenceConvergencePlayed) {
      state.evidenceConvergencePlayed = true;
      playEvidenceConvergence();
    }
  }

  function clearEvidenceConvergence() {
    window.clearTimeout(state.evidenceTimer);
    els.evidenceConvergence.replaceChildren();
    els.evidenceConvergence.dataset.active = "false";
    els.timeMachine.querySelector('[data-timeline="654"]')?.classList.remove("is-receiving-evidence");
  }

  function playEvidenceConvergence() {
    clearEvidenceConvergence();
    const sources = [...els.overlay.querySelectorAll(".moment-box.ignored")];
    const target = els.timeMachine.querySelector('[data-timeline="654"]');
    if (!sources.length || !target || reduceMotion.matches) return;
    const targetRect = target.getBoundingClientRect();
    const targetX = targetRect.left + targetRect.width / 2;
    const targetY = targetRect.top + targetRect.height / 2;
    const waveCounts = [Math.min(12, sources.length), Math.min(16, Math.max(0, sources.length - 12)), Math.max(0, sources.length - 28)];
    const waveStarts = [0, 210, 430];
    sources.forEach((source, index) => {
      const sourceRect = source.getBoundingClientRect();
      const wave = index < 12 ? 0 : index < 28 ? 1 : 2;
      const indexInWave = wave === 0 ? index : wave === 1 ? index - 12 : index - 28;
      const ghost = document.createElement("i");
      ghost.className = "evidence-ghost";
      ghost.dataset.wave = String(wave + 1);
      const width = Math.max(5, sourceRect.width);
      const height = Math.max(5, sourceRect.height);
      const startX = sourceRect.left;
      const startY = sourceRect.top;
      const deltaX = targetX - (startX + width / 2);
      const deltaY = targetY - (startY + height / 2);
      const delay = waveStarts[wave] + indexInWave % 7 * 11;
      ghost.style.left = `${startX}px`;
      ghost.style.top = `${startY}px`;
      ghost.style.width = `${width}px`;
      ghost.style.height = `${height}px`;
      ghost.style.setProperty("--evidence-dx", `${deltaX}px`);
      ghost.style.setProperty("--evidence-dy", `${deltaY}px`);
      ghost.style.setProperty("--evidence-dx-35", `${deltaX * .35}px`);
      ghost.style.setProperty("--evidence-dy-35", `${deltaY * .35}px`);
      ghost.style.setProperty("--evidence-dx-82", `${deltaX * .82}px`);
      ghost.style.setProperty("--evidence-dy-82", `${deltaY * .82}px`);
      ghost.style.setProperty("--evidence-delay", `${delay}ms`);
      ghost.style.setProperty("--evidence-duration", `${420 - wave * 20}ms`);
      els.evidenceConvergence.append(ghost);
    });
    els.evidenceConvergence.dataset.active = "true";
    els.evidenceConvergence.dataset.evidenceCount = String(sources.length);
    els.evidenceConvergence.dataset.waveCounts = waveCounts.join(",");
    target.classList.add("is-receiving-evidence");
    state.evidenceTimer = window.setTimeout(() => clearEvidenceConvergence(), 920);
  }

  function animateTimelineProgress(from, to, duration) {
    if (reduceMotion.matches) {
      applyTimelineProgress(to);
      return Promise.resolve();
    }
    const startedAt = performance.now();
    return new Promise((resolve) => {
      function frame(now) {
        const progress = clamp((now - startedAt) / duration);
        const eased = progress < .5 ? 2 * progress * progress : 1 - Math.pow(-2 * progress + 2, 2) / 2;
        applyTimelineProgress(from + (to - from) * eased);
        if (progress < 1) requestAnimationFrame(frame);
        else resolve();
      }
      requestAnimationFrame(frame);
    });
  }

  function validateFile(file) {
    if (!file) {
      throw new Error("没有读取到图片文件。");
    }
    if (!/^image\/(png|jpeg|webp)$/.test(file.type)) {
      throw new Error("请选择 PNG、JPG 或 WebP 图片。");
    }
    if (file.size > MAX_FILE_SIZE) {
      throw new Error("图片超过 50MB，请选择更小的截图。");
    }
  }

  function nextPaint() {
    return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  }

  async function discardCurrentRun() {
    const runId = state.payload?.run_id;
    if (!runId) {
      return;
    }
    state.payload = null;
    try {
      await fetch(`${BACKEND_API}/discard?run_id=${encodeURIComponent(runId)}`, { method: "POST" });
    } catch (_error) {
      // The backend also expires in-memory runs by TTL.
    }
  }

  async function showImage(file) {
    if (state.imageUrl) {
      URL.revokeObjectURL(state.imageUrl);
    }
    state.imageUrl = URL.createObjectURL(file);
    els.sourceImage.src = state.imageUrl;
    await els.sourceImage.decode();
    els.imageStage.classList.remove("is-empty");
    els.overlay.setAttribute("viewBox", `0 0 ${els.sourceImage.naturalWidth} ${els.sourceImage.naturalHeight}`);
    els.imageName.textContent = file.name;
    els.imageMeta.textContent = `${els.sourceImage.naturalWidth} × ${els.sourceImage.naturalHeight} · ${formatBytes(file.size)}`;
    els.coordinateFieldSize.textContent = `${els.sourceImage.naturalWidth} × ${els.sourceImage.naturalHeight}`;
  }

  function fitImageSurface() {
    const imageWidth = els.sourceImage.naturalWidth;
    const imageHeight = els.sourceImage.naturalHeight;
    if (!imageWidth || !imageHeight || els.imageStage.clientWidth <= 0 || els.imageStage.clientHeight <= 0) {
      return;
    }
    const stageStyle = getComputedStyle(els.imageStage);
    const availableWidth = Math.max(1, els.imageStage.clientWidth - parseFloat(stageStyle.paddingLeft) - parseFloat(stageStyle.paddingRight));
    const availableHeight = Math.max(1, els.imageStage.clientHeight - parseFloat(stageStyle.paddingTop) - parseFloat(stageStyle.paddingBottom));
    const scale = Math.min(availableWidth / imageWidth, availableHeight / imageHeight);
    els.imageSurface.style.width = `${Math.max(1, Math.floor(imageWidth * scale))}px`;
    els.imageSurface.style.height = `${Math.max(1, Math.floor(imageHeight * scale))}px`;
  }

  async function morphToAnalysis() {
    const start = els.dropZone.getBoundingClientRect();
    const capsule = document.createElement("div");
    capsule.className = "morph-capsule";
    capsule.style.cssText = `left:${start.left}px;top:${start.top}px;width:${start.width}px;height:${start.height}px`;
    const preview = document.createElement("img");
    preview.src = state.imageUrl;
    preview.alt = "";
    const lockText = document.createElement("span");
    lockText.textContent = `TARGET ACQUIRED\n${els.sourceImage.naturalWidth} × ${els.sourceImage.naturalHeight}\nUI CAPTURE LOCKED`;
    lockText.style.whiteSpace = "pre-line";
    capsule.append(preview, lockText);
    document.body.append(capsule);

    document.body.classList.add("is-analysis-mode");
    els.landingView.hidden = true;
    els.analysisView.hidden = false;
    els.analysisView.classList.add("is-arriving");
    await nextPaint();
    fitImageSurface();
    const end = els.imageStage.getBoundingClientRect();
    if (!reduceMotion.matches && capsule.animate) {
      const animation = capsule.animate([
        { left: `${start.left}px`, top: `${start.top}px`, width: `${start.width}px`, height: `${start.height}px`, borderRadius: "28px" },
        { left: `${end.left}px`, top: `${end.top}px`, width: `${end.width}px`, height: `${end.height}px`, borderRadius: "14px" },
      ], { duration: 780, easing: "cubic-bezier(.2,.72,.18,1)", fill: "forwards" });
      await animation.finished.catch(() => undefined);
    }
    capsule.remove();
    els.analysisView.classList.remove("is-arriving");
    els.dropZone.classList.remove("is-acquiring");
    fitImageSurface();
  }

  async function requestDetection(file) {
    let response;
    try {
      response = await fetch(
        `${BACKEND_API}/detect?image_name=${encodeURIComponent(file.name)}`,
        { method: "POST", headers: { "Content-Type": file.type }, body: file },
      );
    } catch (_error) {
      throw new Error("无法连接本地 detector。请通过项目启动脚本打开 Jingwei。");
    }
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "本地 detector 运行失败。");
    }
    return payload;
  }

  async function startAnalysis(file) {
    if (state.running) {
      return;
    }
    try {
      validateFile(file);
    } catch (error) {
      showLandingError(error.message);
      return;
    }

    await discardCurrentRun();
    state.file = file;
    state.items = [];
    state.selectedId = null;
    state.filter = "all";
    state.running = true;
    state.startedAt = performance.now();
    state.summary = null;
    resetAnalysisView();
    els.newImageButton.disabled = true;
    els.analysisTitle.textContent = "Jingwei 正在观察这张界面";

    try {
      els.dropZone.classList.add("is-acquiring");
      activateStage("read", "正在解码本地图像…");
      await showImage(file);
      await morphToAnalysis();
      setScan("正在读取图像…", true, "LOCK · TARGET ACQUIRED");
      completeStage("read", `已读取 ${els.sourceImage.naturalWidth} × ${els.sourceImage.naturalHeight} 图像`);

      activateStage("analyze", "本地 detector 正在运行…");
      setScan("正在观察界面结构…");
      const payload = await requestDetection(file);
      state.payload = payload;
      state.items = rules.buildResultItems(payload);
      const summary = rules.buildSummary(payload, state.items);
      state.summary = summary;
      const elapsed = Number(payload.report?.elapsed_ms || performance.now() - state.startedAt);
      completeStage("analyze", `真实检测耗时 ${formatElapsed(elapsed)}`);
      els.elapsedTime.textContent = formatElapsed(elapsed);

      updateCounts(summary);
      await playMoment(summary, elapsed);
    } catch (error) {
      els.dropZone.classList.remove("is-acquiring");
      if (els.analysisView.hidden) {
        showLandingError(error.message);
      } else {
        els.analysisTitle.textContent = "这次分析没有完成";
        els.pipelineNote.textContent = error.message;
        els.pipelineNote.classList.add("is-error");
        setScan("分析失败", false, "SCAN · ABORTED");
      }
    } finally {
      state.running = false;
      els.newImageButton.disabled = false;
      els.replayButton.disabled = !state.summary;
    }
  }

  async function playMoment(summary, elapsed) {
    const rejected = Math.max(0, summary.initial - summary.final);
    window.clearTimeout(state.selectionTimer);
    window.clearTimeout(state.signalTimer);
    window.clearTimeout(state.locationTimer);
    clearEvidenceConvergence();
    state.evidenceConvergencePlayed = false;
    state.selectedId = null;
    state.hoveredId = null;
    els.lens.hidden = true;
    els.imageStage.classList.remove("is-probing");
    els.analysisSignal.classList.remove("is-active");
    els.explainPanel.classList.remove("is-linked", "is-awakening", "is-complete");
    els.explainEmpty.hidden = false;
    els.explainContent.hidden = true;
    els.decisionBadge.textContent = "等待结果";
    els.summaryPanel.hidden = true;
    window.clearTimeout(state.completionTimer);
    els.momentComplete.hidden = true;
    els.momentComplete.classList.remove("is-visible");
    els.analysisMatrix.hidden = false;
    els.visionStatus.hidden = false;
    els.evidenceDock.hidden = false;
    els.timelineRange.disabled = true;
    els.resultFilters.hidden = true;
    els.matrixInitial.textContent = "0";
    els.matrixRejected.textContent = "0";
    els.matrixRetained.textContent = "0";
    els.matrixRate.textContent = "0.0%";
    els.statusVision.textContent = `${els.sourceImage.naturalWidth} × ${els.sourceImage.naturalHeight}`;
    els.statusCandidates.textContent = "0";
    els.statusTime.textContent = formatElapsed(elapsed);
    els.statusState.textContent = "SCANNING";
    els.imageStage.classList.remove("is-scanning", "is-structure");
    renderOverlay();
    renderSignalCloud(summary.initial);
    fitImageSurface();
    applyTimelineProgress(0);
    await nextPaint();

    activateStage("candidates", `正在解析 ${summary.initial} 个真实信号`);
    setScan("经纬坐标正在扫描…", true, "SCAN · SIGNAL SEARCH");
    applyTimelineProgress(125);
    await animateTimelineProgress(125, 422, 1250);
    completeStage("candidates", `发现 ${summary.initial.toLocaleString("en-US")} 个初始候选区域`);

    activateStage("filter", `正在淘汰 ${rejected} 个无效或重复信号`);
    setScan("无效信号正在熄灭…", true, "FILTER · REJECTING");
    await animateTimelineProgress(422, 654, 950);
    completeStage("filter", `已过滤 ${rejected.toLocaleString("en-US")} 个无效或重复区域`);

    activateStage("final", `正在锁定 ${summary.final} 个最终建议`);
    setScan(`${summary.final} 个行动区域正在锁定…`, true, "LOCK · RETAINING");
    await animateTimelineProgress(654, 1000, 950);
    completeStage("final", `最终锁定 ${summary.final.toLocaleString("en-US")} 个建议区域`);
    els.imageStage.classList.remove("is-scanning");
    setScan(`${summary.final} ACTION REGIONS RETAINED`, false, "RETAIN · COMPLETE");
    els.statusState.textContent = "COMPLETE";
    els.resultFilters.hidden = false;
    els.timelineRange.disabled = false;
    finishAnalysis(summary);
  }

  async function replayAnalysis() {
    if (!state.summary || state.running) {
      return;
    }
    state.running = true;
    state.replaying = true;
    els.pipelineList.classList.add("is-replaying");
    els.replayButton.disabled = true;
    els.newImageButton.disabled = true;
    resetPipeline();
    completeStage("read", `已锁定 ${els.sourceImage.naturalWidth} × ${els.sourceImage.naturalHeight} 图像`);
    completeStage("analyze", "复用本次真实 detector 结果");
    els.analysisTitle.textContent = "Jingwei 正在重播这次分析";
    try {
      const elapsed = Number(state.payload?.report?.elapsed_ms || 0);
      await playMoment(state.summary, elapsed);
    } finally {
      state.replaying = false;
      els.pipelineList.classList.remove("is-replaying");
      els.imageStage.classList.remove("is-scanning", "is-structure");
      state.running = false;
      els.replayButton.disabled = false;
      els.newImageButton.disabled = false;
    }
  }

  function resetAnalysisView() {
    resetPipeline();
    els.overlay.replaceChildren();
    els.overlay.classList.remove("is-filtered");
    window.clearTimeout(state.selectionTimer);
    window.clearTimeout(state.signalTimer);
    window.clearTimeout(state.locationTimer);
    clearEvidenceConvergence();
    window.clearTimeout(state.retainTimer);
    window.clearTimeout(state.completingTimer);
    state.replaying = false;
    els.pipelineList.classList.remove("is-replaying");
    els.analysisSignal.classList.remove("is-active");
    els.imageStage.classList.remove("is-scanning", "is-structure");
    els.imageStage.classList.add("is-empty");
    els.resultFilters.hidden = true;
    els.analysisMatrix.hidden = true;
    els.visionStatus.hidden = true;
    els.evidenceDock.hidden = true;
    window.clearTimeout(state.completionTimer);
    els.momentComplete.hidden = true;
    els.momentComplete.classList.remove("is-visible");
    els.signalCloud.replaceChildren();
    els.signalCloud.style.opacity = "0";
    els.lens.hidden = true;
    els.ghostModeBadge.hidden = true;
    els.imageStage.classList.remove("is-ghost-mode", "is-probing");
    state.ghostMode = false;
    state.timelineProgress = 0;
    els.summaryPanel.hidden = true;
    els.explainEmpty.hidden = false;
    els.explainContent.hidden = true;
    els.decisionBadge.textContent = "等待结果";
    els.explainPanel.classList.remove("is-linked", "is-awakening", "is-complete");
    els.pipelineNote.textContent = "所有阶段均由真实图像事件或 detector 结果触发。";
    els.pipelineNote.classList.remove("is-error");
    els.elapsedTime.textContent = "—";
    els.reviewButtons.forEach((button) => { button.disabled = true; });
    els.replayButton.disabled = true;
    els.resultFilters.querySelectorAll("button").forEach((button) => button.classList.toggle("is-active", button.dataset.filter === "all"));
  }

  function finishAnalysis(summary) {
    els.analysisTitle.textContent = "Jingwei 已完成这张界面的分析";
    els.summaryText.textContent = summary.text;
    els.pageStateText.textContent = summary.pageState;
    els.summaryPanel.hidden = false;
    els.reviewButtons.forEach((button) => { button.disabled = false; });
    els.replayButton.disabled = false;
    els.timelineRange.disabled = false;
    window.clearTimeout(state.completingTimer);
    els.evidenceDock.classList.remove("is-completing");
    els.explainPanel.classList.remove("is-complete");
    els.matrixRetained.parentElement.classList.remove("is-settling");
    void els.evidenceDock.getBoundingClientRect();
    els.evidenceDock.classList.add("is-completing");
    els.explainPanel.classList.add("is-complete");
    els.matrixRetained.parentElement.classList.add("is-settling");
    state.completingTimer = window.setTimeout(() => {
      els.evidenceDock.classList.remove("is-completing");
      els.explainPanel.classList.remove("is-complete");
      els.matrixRetained.parentElement.classList.remove("is-settling");
    }, reduceMotion.matches ? 20 : 1250);
    els.momentCompleteCount.textContent = summary.final.toLocaleString("en-US");
    els.momentComplete.hidden = false;
    els.momentComplete.classList.remove("is-visible");
    void els.momentComplete.offsetWidth;
    els.momentComplete.classList.add("is-visible");
    window.clearTimeout(state.completionTimer);
    state.completionTimer = window.setTimeout(() => {
      els.momentComplete.classList.remove("is-visible");
      els.momentComplete.hidden = true;
    }, reduceMotion.matches ? 30 : 1350);
  }

  function updateCounts(summary) {
    els.counts.all.textContent = String(state.items.length);
    els.counts.keep.textContent = String(summary.keep);
    els.counts.pending.textContent = String(summary.pending);
    els.counts.ignored.textContent = String(summary.ignored);
    els.counts.summaryKeep.textContent = String(summary.keep);
    els.counts.summaryPending.textContent = String(summary.pending);
    els.counts.summaryIgnored.textContent = String(summary.ignored);
  }

  function renderOverlay() {
    els.overlay.replaceChildren();
    els.overlay.classList.remove("is-filtered");
    const ignoredItems = state.items.filter((item) => item.decision === "ignored");
    const retainedItems = state.items.filter((item) => item.decision !== "ignored");
    const renderItems = [...ignoredItems, ...retainedItems];
    for (const candidate of renderItems) {
      const index = state.items.indexOf(candidate);
      const box = candidate.bbox;
      if (!box || box.width <= 0 || box.height <= 0) {
        continue;
      }
      const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
      group.setAttribute("class", `moment-box ${candidate.decision}`);
      group.setAttribute("data-moment-id", candidate.moment_id);
      group.setAttribute("tabindex", "0");
      group.setAttribute("role", "button");
      group.setAttribute("aria-label", `${candidate.id} ${decisionName(candidate.decision)}`);

      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("x", box.x);
      rect.setAttribute("y", box.y);
      rect.setAttribute("width", box.width);
      rect.setAttribute("height", box.height);
      rect.setAttribute("rx", Math.min(8, box.width / 8, box.height / 8));
      const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
      title.textContent = `${candidate.id} · ${decisionName(candidate.decision)} · ${Math.round(Number(candidate.score || 0) * 100)}%`;
      rect.append(title);

      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("x", box.x + 4);
      label.setAttribute("y", Math.max(14, box.y - 5));
      label.textContent = candidate.decision === "ignored" ? `忽略 ${index + 1}` : String(index + 1);
      group.append(rect, label);
      group.addEventListener("click", () => selectCandidate(candidate.moment_id));
      group.addEventListener("pointerenter", (event) => showCandidateLens(candidate, event));
      group.addEventListener("pointerover", (event) => showCandidateLens(candidate, event));
      group.addEventListener("pointermove", (event) => positionLens(event));
      group.addEventListener("pointerleave", hideCandidateLens);
      group.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectCandidate(candidate.moment_id);
        }
      });
      els.overlay.append(group);
    }
    updateOverlayVisibility();
    applyTimelineProgress(state.timelineProgress * 1000);
  }

  function transmitCandidateSignal(momentId) {
    window.clearTimeout(state.signalTimer);
    const source = els.overlay.querySelector(`[data-moment-id="${CSS.escape(momentId)}"]`);
    const target = els.explainEmpty.querySelector(".reason-core");
    if (!source || !target || reduceMotion.matches) {
      els.analysisSignal.classList.remove("is-active");
      return;
    }
    const gridRect = els.analysisGrid.getBoundingClientRect();
    const sourceRect = source.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    const startX = sourceRect.right - gridRect.left;
    const startY = sourceRect.top + sourceRect.height / 2 - gridRect.top;
    const endX = targetRect.left + targetRect.width / 2 - gridRect.left;
    const endY = targetRect.top + targetRect.height / 2 - gridRect.top;
    const bend = Math.max(54, (endX - startX) * .42);
    const pathData = `M ${startX} ${startY} C ${startX + bend} ${startY}, ${endX - bend} ${endY}, ${endX} ${endY}`;
    const path = els.analysisSignal.querySelector("path");
    const dot = els.analysisSignal.querySelector("circle");
    els.analysisSignal.setAttribute("viewBox", `0 0 ${gridRect.width} ${gridRect.height}`);
    path.setAttribute("d", pathData);
    path.setAttribute("pathLength", "1");
    dot.replaceChildren();
    const motion = document.createElementNS("http://www.w3.org/2000/svg", "animateMotion");
    motion.setAttribute("dur", "300ms");
    motion.setAttribute("fill", "freeze");
    motion.setAttribute("path", pathData);
    dot.append(motion);
    els.analysisSignal.classList.remove("is-active");
    void els.analysisSignal.getBoundingClientRect();
    els.analysisSignal.classList.add("is-active");
    motion.beginElement?.();
    state.signalTimer = window.setTimeout(() => els.analysisSignal.classList.remove("is-active"), 360);
  }

  function selectCandidate(momentId) {
    const candidate = state.items.find((item) => item.moment_id === momentId);
    if (!candidate) {
      return;
    }
    hideCandidateLens();
    window.clearTimeout(state.selectionTimer);
    window.clearTimeout(state.locationTimer);
    window.clearTimeout(state.signalTimer);
    state.selectedId = momentId;
    const explanation = rules.explainCandidate(candidate);
    els.explainEmpty.hidden = false;
    els.explainContent.hidden = true;
    els.explainPanel.classList.remove("is-linked", "is-awakening");
    void els.explainPanel.getBoundingClientRect();
    els.explainPanel.classList.add("is-awakening");
    els.decisionBadge.textContent = "解析证据";
    els.reasonCoreResult.textContent = `${Math.round(explanation.confidence * 100)}%`;
    els.candidateId.textContent = candidate.id;
    els.candidateType.textContent = explanation.type;
    els.candidateDecision.textContent = explanation.decision;
    els.candidateConfidence.textContent = `${confidenceName(explanation.confidence)} · ${Math.round(explanation.confidence * 100)}%`;
    els.confidenceMeter.value = explanation.confidence;
    els.candidateWhy.textContent = explanation.why;
    els.candidateSuggestion.textContent = explanation.suggestion;
    els.reasonTags.replaceChildren();
    (candidate.reasons || []).slice(-6).forEach((reason) => {
      const tag = document.createElement("span");
      tag.textContent = rules.reasonLabel(reason);
      els.reasonTags.append(tag);
    });
    const box = candidate.bbox;
    els.bboxValue.textContent = `x ${box.x}  y ${box.y}  width ${box.width}  height ${box.height}`;
    els.coordinateX.textContent = `X ${String(box.x).padStart(4, "0")}`;
    els.coordinateY.textContent = `Y ${String(box.y).padStart(4, "0")}`;
    els.coordinateBox.textContent = `W ${box.width} · H ${box.height}`;
    renderSelectionGuides(candidate);
    els.overlay.querySelectorAll(".moment-box.is-cross-locating").forEach((group) => group.classList.remove("is-cross-locating"));
    const locatedGroup = els.overlay.querySelector(`[data-moment-id="${CSS.escape(momentId)}"]`);
    locatedGroup?.classList.add("is-cross-locating");
    els.lockFlash.classList.remove("is-visible");
    void els.lockFlash.offsetWidth;
    els.lockFlash.classList.add("is-visible");
    updateOverlayVisibility();
    state.signalTimer = window.setTimeout(() => transmitCandidateSignal(momentId), reduceMotion.matches ? 0 : 310);
    state.locationTimer = window.setTimeout(() => locatedGroup?.classList.remove("is-cross-locating"), reduceMotion.matches ? 0 : 680);
    state.selectionTimer = window.setTimeout(() => {
      if (state.selectedId !== momentId) return;
      els.explainPanel.classList.remove("is-awakening");
      els.explainPanel.classList.add("is-linked");
      els.explainEmpty.hidden = true;
      els.explainContent.hidden = false;
      els.decisionBadge.textContent = explanation.badge;
    }, reduceMotion.matches ? 0 : 680);
  }

  function showCandidateLens(candidate, event) {
    if (state.running || state.timelineProgress < .4) return;
    const explanation = rules.explainCandidate(candidate);
    const box = candidate.bbox;
    state.hoveredId = candidate.moment_id;
    els.lensCoordinate.textContent = `X${String(box.x).padStart(4, "0")} · Y${String(box.y).padStart(4, "0")}`;
    els.lensType.textContent = explanation.type;
    els.lensBbox.textContent = `${box.width} × ${box.height} px`;
    els.lensConfidence.textContent = `${Math.round(explanation.confidence * 100)}%`;
    els.lensWhy.textContent = explanation.why;
    els.lens.hidden = false;
    positionLens(event);
  }

  function positionLens(event) {
    if (els.lens.hidden) return;
    const panelRect = els.imagePanel?.getBoundingClientRect?.() || els.imageStage.getBoundingClientRect();
    const width = 248;
    const height = 210;
    const left = clamp(event.clientX - panelRect.left + 16, 8, Math.max(8, panelRect.width - width - 8));
    const top = clamp(event.clientY - panelRect.top + 16, 8, Math.max(8, panelRect.height - height - 8));
    els.lens.style.left = `${left}px`;
    els.lens.style.top = `${top}px`;
  }

  function hideCandidateLens() {
    state.hoveredId = null;
    els.lens.hidden = true;
  }

  function renderSelectionGuides(candidate) {
    els.overlay.querySelector(".selection-guides")?.remove();
    const box = candidate.bbox;
    const x = box.x + box.width / 2;
    const y = box.y + box.height / 2;
    const width = els.sourceImage.naturalWidth;
    const height = els.sourceImage.naturalHeight;
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    group.setAttribute("class", "selection-guides");
    group.dataset.coordinateX = String(Math.round(x));
    group.dataset.coordinateY = String(Math.round(y));
    group.dataset.duration = reduceMotion.matches ? "0" : "680";
    const line = (x1, y1, x2, y2, axis) => {
      const element = document.createElementNS("http://www.w3.org/2000/svg", "line");
      element.setAttribute("x1", x1);
      element.setAttribute("y1", y1);
      element.setAttribute("x2", x2);
      element.setAttribute("y2", y2);
      element.setAttribute("pathLength", "1");
      element.setAttribute("class", `coordinate-axis axis-${axis}`);
      return element;
    };
    const horizontalLeft = line(0, y, x, y, "horizontal");
    const horizontalRight = line(width, y, x, y, "horizontal");
    const verticalTop = line(x, 0, x, y, "vertical");
    const verticalBottom = line(x, height, x, y, "vertical");
    const center = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    center.setAttribute("class", "coordinate-pulse");
    center.setAttribute("cx", x);
    center.setAttribute("cy", y);
    center.setAttribute("r", Math.max(4, Math.min(width, height) * .006));
    const xLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
    xLabel.setAttribute("class", "axis-coordinate");
    xLabel.setAttribute("x", x + 7);
    xLabel.setAttribute("y", "16");
    xLabel.textContent = `X = ${String(Math.round(x)).padStart(4, "0")}`;
    const yLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
    yLabel.setAttribute("class", "axis-coordinate");
    yLabel.setAttribute("x", "7");
    yLabel.setAttribute("y", Math.max(16, y - 7));
    yLabel.textContent = `Y = ${String(Math.round(y)).padStart(4, "0")}`;
    const cornerSize = Math.max(4, Math.min(12, box.width * .24, box.height * .24));
    const cornerPaths = [
      `M ${box.x} ${box.y + cornerSize} L ${box.x} ${box.y} L ${box.x + cornerSize} ${box.y}`,
      `M ${box.x + box.width - cornerSize} ${box.y} L ${box.x + box.width} ${box.y} L ${box.x + box.width} ${box.y + cornerSize}`,
      `M ${box.x + box.width} ${box.y + box.height - cornerSize} L ${box.x + box.width} ${box.y + box.height} L ${box.x + box.width - cornerSize} ${box.y + box.height}`,
      `M ${box.x + cornerSize} ${box.y + box.height} L ${box.x} ${box.y + box.height} L ${box.x} ${box.y + box.height - cornerSize}`,
    ].map((pathData) => {
      const corner = document.createElementNS("http://www.w3.org/2000/svg", "path");
      corner.setAttribute("class", "coordinate-corner");
      corner.setAttribute("d", pathData);
      corner.setAttribute("pathLength", "1");
      return corner;
    });
    group.append(horizontalLeft, horizontalRight, verticalTop, verticalBottom, center, xLabel, yLabel, ...cornerPaths);
    els.overlay.prepend(group);
  }

  function updateOverlayVisibility() {
    els.overlay.querySelectorAll(".moment-box").forEach((group) => {
      const candidate = state.items.find((item) => item.moment_id === group.dataset.momentId);
      const filteredOut = state.filter !== "all" && candidate?.decision !== state.filter;
      const ghostVisible = state.ghostMode && candidate?.decision === "ignored";
      group.classList.toggle("is-hidden", filteredOut && !ghostVisible);
      group.classList.toggle("is-selected", candidate?.moment_id === state.selectedId);
      group.classList.toggle("is-dimmed", Boolean(state.selectedId) && candidate?.moment_id !== state.selectedId);
    });
    applyTimelineProgress(state.timelineProgress * 1000);
  }

  function updateCoordinateProbe(event) {
    if (!state.file || els.analysisView.hidden) return;
    const imageRect = els.sourceImage.getBoundingClientRect();
    const stageRect = els.imageStage.getBoundingClientRect();
    const inside = event.clientX >= imageRect.left && event.clientX <= imageRect.right && event.clientY >= imageRect.top && event.clientY <= imageRect.bottom;
    els.imageStage.classList.toggle("is-probing", inside);
    if (!inside) return;
    const relativeX = clamp((event.clientX - imageRect.left) / Math.max(1, imageRect.width));
    const relativeY = clamp((event.clientY - imageRect.top) / Math.max(1, imageRect.height));
    const imageX = Math.round(relativeX * els.sourceImage.naturalWidth);
    const imageY = Math.round(relativeY * els.sourceImage.naturalHeight);
    const probeX = event.clientX - stageRect.left;
    const probeY = event.clientY - stageRect.top;
    els.imageStage.style.setProperty("--field-x", `${clamp(probeX / Math.max(1, stageRect.width)) * 100}%`);
    els.imageStage.style.setProperty("--field-y", `${clamp(probeY / Math.max(1, stageRect.height)) * 100}%`);
    els.probe.style.setProperty("--probe-x", `${probeX}px`);
    els.probe.style.setProperty("--probe-y", `${probeY}px`);
    els.probe.querySelector(".probe-x").textContent = `X ${String(imageX).padStart(4, "0")}`;
    els.probe.querySelector(".probe-y").textContent = `Y ${String(imageY).padStart(4, "0")}`;
    els.coordinateX.textContent = `X ${String(imageX).padStart(4, "0")}`;
    els.coordinateY.textContent = `Y ${String(imageY).padStart(4, "0")}`;
    const hoveredGroup = event.target.closest?.(".moment-box");
    const hoveredCandidate = hoveredGroup
      ? state.items.find((item) => item.moment_id === hoveredGroup.dataset.momentId)
      : null;
    if (hoveredCandidate) {
      showCandidateLens(hoveredCandidate, event);
    } else if (state.hoveredId) {
      hideCandidateLens();
    }
  }

  function setGhostMode(active) {
    const available = Boolean(state.summary && state.items.some((item) => item.decision === "ignored"));
    const nextGhostMode = Boolean(active && available);
    if (nextGhostMode && !state.ghostMode) {
      state.ghostActivations += 1;
      els.imageStage.dataset.ghostActivations = String(state.ghostActivations);
    }
    state.ghostMode = nextGhostMode;
    els.imageStage.classList.toggle("is-ghost-mode", state.ghostMode);
    els.ghostModeBadge.hidden = !state.ghostMode;
    if (!state.ghostMode && state.hoveredId?.startsWith("ignored:")) hideCandidateLens();
    updateOverlayVisibility();
  }

  function showLandingError(message) {
    const original = els.dropZone.querySelector(":scope > span");
    original.textContent = message;
    els.dropZone.classList.add("has-error");
  }

  function returnToLanding() {
    if (state.running) {
      return;
    }
    discardCurrentRun();
    if (state.imageUrl) {
      URL.revokeObjectURL(state.imageUrl);
      state.imageUrl = null;
    }
    state.file = null;
    state.items = [];
    state.selectedId = null;
    state.summary = null;
    els.imageInput.value = "";
    els.analysisView.hidden = true;
    els.landingView.hidden = false;
    document.body.classList.remove("is-analysis-mode");
    els.imageSurface.style.width = "1px";
    els.imageSurface.style.height = "1px";
  }

  function openHandoffDatabase() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(HANDOFF_DB, 1);
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains(HANDOFF_STORE)) {
          request.result.createObjectStore(HANDOFF_STORE);
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async function storeHandoff() {
    if (!state.file || !state.payload) {
      return;
    }
    const database = await openHandoffDatabase();
    await new Promise((resolve, reject) => {
      const transaction = database.transaction(HANDOFF_STORE, "readwrite");
      transaction.objectStore(HANDOFF_STORE).put(
        {
          image: state.file,
          image_name: state.file.name,
          image_type: state.file.type,
          payload: state.payload,
          selected_candidate_id: state.items.find((item) => item.moment_id === state.selectedId && item.decision !== "ignored")?.id || state.items.find((item) => item.decision !== "ignored")?.id || null,
          timeline_progress: state.timelineProgress,
          created_at: new Date().toISOString(),
        },
        HANDOFF_KEY,
      );
      transaction.oncomplete = resolve;
      transaction.onerror = () => reject(transaction.error);
    });
    database.close();
  }

  async function enterProfessionalReview() {
    if (!state.payload || !state.file || state.handingOff) {
      return;
    }
    state.handingOff = true;
    els.reviewButtons.forEach((button) => { button.disabled = true; button.textContent = "正在交接结果…"; });
    try {
      await storeHandoff();
      els.analysisView.classList.add("is-handing-off");
      els.reviewButtons.forEach((button) => { button.textContent = "正在进入专业工作台…"; });
      await sleep(640);
      window.location.href = "./index.html?from=moment";
    } catch (_error) {
      state.handingOff = false;
      els.analysisView.classList.remove("is-handing-off");
      els.pipelineNote.textContent = "无法准备专业审核交接，请重新尝试。";
      els.pipelineNote.classList.add("is-error");
      els.reviewButtons.forEach((button) => { button.disabled = false; button.textContent = button.id === "reviewButton" ? "带着结果进入专业审核" : "进入专业审核"; });
    }
  }

  function createSampleImage() {
    const canvas = document.createElement("canvas");
    canvas.width = 720;
    canvas.height = 1280;
    const context = canvas.getContext("2d");
    const gradient = context.createLinearGradient(0, 0, 720, 1280);
    gradient.addColorStop(0, "#f1f6ff");
    gradient.addColorStop(1, "#dce9ff");
    context.fillStyle = gradient;
    context.fillRect(0, 0, 720, 1280);
    context.fillStyle = "#10396f";
    context.fillRect(0, 0, 720, 130);
    context.fillStyle = "#ffffff";
    context.font = "700 30px sans-serif";
    context.fillText("Jingwei Travel", 42, 72);
    context.fillStyle = "#39d7b5";
    context.beginPath();
    context.arc(650, 65, 24, 0, Math.PI * 2);
    context.fill();
    drawCard(context, 38, 172, 644, 280, "下一站 · 海岸公路", "今天 14:30 出发");
    drawButton(context, 72, 492, 576, 92, "查看行程", "#0875ed");
    drawCard(context, 38, 630, 306, 230, "酒店", "已确认 · 2 晚");
    drawCard(context, 376, 630, 306, 230, "租车", "取车码 3851");
    context.fillStyle = "rgba(255,255,255,.92)";
    roundRect(context, 38, 900, 644, 210, 26);
    context.fill();
    context.fillStyle = "#123b70";
    context.font = "700 25px sans-serif";
    context.fillText("出发前提醒", 70, 955);
    context.font = "20px sans-serif";
    context.fillStyle = "#627a99";
    context.fillText("证件、充电器、离线地图", 70, 1000);
    drawButton(context, 455, 1025, 180, 54, "我知道了", "#16a36b");
    context.fillStyle = "#ffffff";
    context.fillRect(0, 1170, 720, 110);
    [92, 270, 450, 628].forEach((x, index) => {
      context.fillStyle = index === 0 ? "#0875ed" : "#94a6bc";
      context.beginPath();
      context.arc(x, 1212, 15, 0, Math.PI * 2);
      context.fill();
      context.font = "16px sans-serif";
      context.fillText(["首页", "行程", "消息", "我的"][index], x - 18, 1254);
    });
    return new Promise((resolve, reject) => {
      canvas.toBlob((blob) => {
        if (!blob) {
          reject(new Error("无法生成示例图片。"));
          return;
        }
        resolve(new File([blob], "jingwei-moment-sample.png", { type: "image/png" }));
      }, "image/png");
    });
  }

  function drawCard(context, x, y, width, height, title, subtitle) {
    context.fillStyle = "rgba(255,255,255,.94)";
    roundRect(context, x, y, width, height, 28);
    context.fill();
    context.strokeStyle = "#c8d9ef";
    context.lineWidth = 2;
    context.stroke();
    context.fillStyle = "#123b70";
    context.font = "700 27px sans-serif";
    context.fillText(title, x + 34, y + 70);
    context.fillStyle = "#7186a2";
    context.font = "19px sans-serif";
    context.fillText(subtitle, x + 34, y + 112);
    context.fillStyle = "#e6f0ff";
    roundRect(context, x + 34, y + 148, width - 68, height - 182, 18);
    context.fill();
  }

  function drawButton(context, x, y, width, height, label, color) {
    context.fillStyle = color;
    roundRect(context, x, y, width, height, Math.min(22, height / 2));
    context.fill();
    context.fillStyle = "#ffffff";
    context.font = `700 ${Math.max(18, Math.round(height * 0.3))}px sans-serif`;
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(label, x + width / 2, y + height / 2);
    context.textAlign = "start";
    context.textBaseline = "alphabetic";
  }

  function roundRect(context, x, y, width, height, radius) {
    context.beginPath();
    context.roundRect(x, y, width, height, radius);
  }

  function formatBytes(bytes) {
    if (bytes < 1024 * 1024) {
      return `${Math.max(1, Math.round(bytes / 1024))}KB`;
    }
    return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
  }

  function formatElapsed(milliseconds) {
    return milliseconds >= 1000 ? `${(milliseconds / 1000).toFixed(2)}s` : `${Math.round(milliseconds)}ms`;
  }

  function decisionName(decision) {
    return { keep: "建议保留", pending: "需要确认", ignored: "规则忽略" }[decision] || decision;
  }

  function confidenceName(score) {
    if (score >= 0.75) return "高";
    if (score >= 0.45) return "中";
    return "低";
  }

  async function refreshHealth() {
    let online = false;
    try {
      const response = await fetch(`${BACKEND_API}/health`, { cache: "no-store" });
      const payload = await response.json();
      online = response.ok && payload.app === "hotarea-cv" && payload.capabilities?.includes("detect");
    } catch (_error) {
      online = false;
    }
    els.runtimeBadge.classList.remove("is-checking");
    els.runtimeBadge.classList.toggle("is-offline", !online);
    els.runtimeBadge.querySelector("span").textContent = online ? "本地模型已连接" : "本地模型未连接";
  }

  els.chooseButton.addEventListener("click", (event) => { event.stopPropagation(); els.imageInput.click(); });
  els.sampleButton.addEventListener("click", async (event) => { event.stopPropagation(); startAnalysis(await createSampleImage()); });
  els.dropZone.addEventListener("click", (event) => { if (!event.target.closest("button")) els.imageInput.click(); });
  els.dropZone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      els.imageInput.click();
    }
  });
  for (const eventName of ["dragenter", "dragover"]) {
    els.dropZone.addEventListener(eventName, (event) => { event.preventDefault(); els.dropZone.classList.add("is-dragging"); });
  }
  for (const eventName of ["dragleave", "drop"]) {
    els.dropZone.addEventListener(eventName, (event) => { event.preventDefault(); els.dropZone.classList.remove("is-dragging"); });
  }
  els.dropZone.addEventListener("drop", (event) => startAnalysis(event.dataTransfer?.files?.[0]));
  els.imageInput.addEventListener("change", (event) => startAnalysis(event.target.files?.[0]));
  els.newImageButton.addEventListener("click", returnToLanding);
  els.replayButton.addEventListener("click", replayAnalysis);
  els.timelineRange.addEventListener("input", (event) => {
    if (!state.summary || state.running) return;
    hideCandidateLens();
    applyTimelineProgress(Number(event.target.value));
  });
  function seekTimelineFromPointer(event) {
    const rect = els.timelineControl.getBoundingClientRect();
    const progress = clamp((event.clientX - rect.left) / Math.max(1, rect.width));
    hideCandidateLens();
    applyTimelineProgress(progress * 1000);
  }
  els.timelineControl.addEventListener("pointerdown", (event) => {
    if (!state.summary || state.running) return;
    state.timelineDragging = true;
    els.timelineControl.setPointerCapture?.(event.pointerId);
    seekTimelineFromPointer(event);
    event.preventDefault();
  });
  els.timelineControl.addEventListener("pointermove", (event) => {
    if (!state.timelineDragging) return;
    seekTimelineFromPointer(event);
  });
  for (const eventName of ["pointerup", "pointercancel"]) {
    els.timelineControl.addEventListener(eventName, (event) => {
      state.timelineDragging = false;
      els.timelineControl.releasePointerCapture?.(event.pointerId);
    });
  }
  els.timeMachine.querySelector(".timeline-markers").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-timeline]");
    if (!button || state.running || !state.summary) return;
    applyTimelineProgress(Number(button.dataset.timeline));
  });
  els.imageStage.addEventListener("pointermove", updateCoordinateProbe);
  els.imageStage.addEventListener("pointermove", updateMagneticField, { passive: true });
  els.imageStage.addEventListener("pointerleave", () => {
    els.imageStage.classList.remove("is-probing");
    els.imageStage.style.setProperty("--field-x", "50%");
    els.imageStage.style.setProperty("--field-y", "50%");
    releaseMagneticField();
    hideCandidateLens();
  });
  window.addEventListener("pointermove", releaseMagneticFieldIfOutside, { passive: true });
  window.addEventListener("pointerdown", releaseMagneticFieldIfOutside, { passive: true });
  window.addEventListener("blur", releaseMagneticField);
  els.reviewButtons.forEach((button) => button.addEventListener("click", enterProfessionalReview));
  els.resultFilters.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-filter]");
    if (!button) return;
    state.filter = button.dataset.filter;
    els.resultFilters.querySelectorAll("button").forEach((item) => item.classList.toggle("is-active", item === button));
    updateOverlayVisibility();
  });
  window.addEventListener("beforeunload", () => {
    if (state.handingOff || !state.payload?.run_id) return;
    navigator.sendBeacon(`${BACKEND_API}/discard?run_id=${encodeURIComponent(state.payload.run_id)}`, new Blob([]));
  });
  window.addEventListener("keydown", (event) => {
    if (event.key === "Alt" && !event.repeat && state.summary && !state.handingOff) {
      event.preventDefault();
      setGhostMode(true);
    }
  });
  window.addEventListener("keyup", (event) => {
    if (event.key === "Alt") {
      event.preventDefault();
      setGhostMode(false);
    }
  });
  window.addEventListener("blur", () => setGhostMode(false));
  window.addEventListener("resize", fitImageSurface);
  window.addEventListener("pointermove", (event) => {
    const x = `${event.clientX / Math.max(1, window.innerWidth) * 100}%`;
    const y = `${event.clientY / Math.max(1, window.innerHeight) * 100}%`;
    document.body.style.setProperty("--field-x", x);
    document.body.style.setProperty("--field-y", y);
    const rect = els.dropZone.getBoundingClientRect();
    if (event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom) {
      els.dropZone.style.setProperty("--sensor-x", `${(event.clientX - rect.left) / rect.width * 100}%`);
      els.dropZone.style.setProperty("--sensor-y", `${(event.clientY - rect.top) / rect.height * 100}%`);
    }
  }, { passive: true });

  if ("ResizeObserver" in window) {
    const imageStageObserver = new ResizeObserver(() => {
      fitImageSurface();
      scheduleMagneticField();
    });
    imageStageObserver.observe(els.imageStage);
  }

  scheduleMagneticField();
  refreshHealth();
})();
