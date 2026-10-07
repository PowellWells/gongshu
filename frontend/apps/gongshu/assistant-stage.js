(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const layer = byId("assistantStageLayer");
  const actor = byId("yungangAssistantActor");
  const sprite = byId("yungangAssistantSprite");
  const bubble = byId("yungangAssistantBubble");
  const marker = byId("assistantTargetMarker");
  const toggle = byId("advisorModeToggle");
  const modeState = byId("advisorModeState");
  const settingsButton = byId("advisorSettingsButton");
  const settingsDialog = byId("advisorSettingsDialog");
  const liveStage = document.querySelector(".live-rgb-stage");
  if (!layer || !actor || !sprite || !bubble || !toggle || !modeState) return;

  const STORAGE_KEY = "gongshu_yungang_position";
  const ADVISOR_STORAGE_KEY = "gongshu_advisor_mode";
  const ASSET_BASE = "../../assets/yungang/";
  const SPRITES = Object.freeze({
    idle: `${ASSET_BASE}yungang_idle.png`,
    summon: `${ASSET_BASE}yungang_move.png`,
    move: `${ASSET_BASE}yungang_move.png`,
    dismiss: `${ASSET_BASE}yungang_move.png`,
    "point-left": `${ASSET_BASE}yungang_point_left.png`,
    "point-right": `${ASSET_BASE}yungang_point_right.png`,
  });
  const DEFAULT_FRAME = Object.freeze({ width: 1000, height: 650 });
  const TRANSITION_MS = 430;
  function readAdvisorMode() {
    try {
      const saved = window.localStorage.getItem(ADVISOR_STORAGE_KEY);
      if (saved === "true" || saved === "false") return saved === "true";
    } catch {
      // Use the pet-first default when storage is unavailable.
    }
    return false;
  }

  const state = {
    advisorMode: readAdvisorMode(),
    target: null,
    placement: null,
    position: null,
    homePosition: null,
    visible: false,
    drag: null,
    transitionTimer: 0,
    dismissTimer: 0,
  };

  function finite(value) {
    return Number.isFinite(Number(value));
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), Math.max(min, max));
  }

  function viewportSize() {
    const rect = layer.getBoundingClientRect();
    return {
      width: Math.max(1, rect.width || window.innerWidth),
      height: Math.max(1, rect.height || window.innerHeight),
    };
  }

  function actorSize() {
    const viewport = viewportSize();
    const cssWidth = actor.offsetWidth || actor.getBoundingClientRect().width;
    const width = cssWidth > 0 ? cssWidth : clamp(viewport.width * .11, 78, 142);
    return { width, height: Math.min(viewport.height - 16, width * 4 / 3) };
  }

  function clampPosition(position) {
    const viewport = viewportSize();
    const { width, height } = actorSize();
    return {
      x: clamp(Number(position?.x) || 0, 8, viewport.width - width - 8),
      y: clamp(Number(position?.y) || 0, 8, viewport.height - height - 8),
    };
  }

  function setPosition(position) {
    const next = clampPosition(position);
    state.position = next;
    actor.style.left = `${next.x}px`;
    actor.style.top = `${next.y}px`;
  }

  function restoreHomePosition() {
    if (!state.homePosition || state.drag) return;
    setPosition(state.homePosition);
    state.homePosition = { ...state.position };
  }

  function positionLimits() {
    const viewport = viewportSize();
    const { width, height } = actorSize();
    return {
      maxX: Math.max(1, viewport.width - width - 8),
      maxY: Math.max(1, viewport.height - height - 8),
    };
  }

  function readStoredHomePosition() {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      const saved = JSON.parse(raw);
      if (finite(saved?.xRatio) && finite(saved?.yRatio)) {
        const limits = positionLimits();
        return clampPosition({ x: Number(saved.xRatio) * limits.maxX, y: Number(saved.yRatio) * limits.maxY });
      }
    } catch {
      // Storage can be unavailable in privacy-restricted file or embedded contexts.
    }
    return null;
  }

  function saveHomePosition() {
    if (!state.homePosition) return;
    const limits = positionLimits();
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({
        version: 1,
        xRatio: state.homePosition.x / limits.maxX,
        yRatio: state.homePosition.y / limits.maxY,
      }));
    } catch {
      // The in-memory home position still works for the current page session.
    }
  }

  function defaultHomePosition() {
    const { width, height } = actorSize();
    const stageRect = liveStage?.getBoundingClientRect();
    const viewport = viewportSize();
    if (stageRect && stageRect.width > 0 && stageRect.height > 0) {
      return clampPosition({
        x: stageRect.left + 18,
        y: stageRect.bottom - height - 18,
      });
    }
    return clampPosition({ x: 24, y: viewport.height - height - 24 });
  }

  function setState(nextState) {
    const classes = [
      "assistant-idle",
      "assistant-dragging",
      "assistant-moving",
      "assistant-pointing",
      "assistant-returning",
    ];
    actor.dataset.state = nextState;
    actor.classList.remove(...classes);
    if (nextState === "idle") actor.classList.add("assistant-idle");
    if (nextState === "dragging") actor.classList.add("assistant-dragging");
    if (["summon", "move"].includes(nextState)) actor.classList.add("assistant-moving");
    if (["point-left", "point-right"].includes(nextState)) actor.classList.add("assistant-pointing");
    if (nextState === "dismiss") actor.classList.add("assistant-returning");
    sprite.src = SPRITES[nextState] || SPRITES.idle;
  }

  function setBubble(text) {
    bubble.textContent = text;
  }

  function normalizedTarget(detail = {}) {
    const bbox = Array.isArray(detail.bbox) ? detail.bbox.map(Number) : [];
    const frame = detail.frame || {};
    const width = Number(frame.width);
    const height = Number(frame.height);
    if (bbox.length !== 4 || !bbox.every(finite) || bbox[2] <= bbox[0] || bbox[3] <= bbox[1]) return null;
    if (!finite(width) || !finite(height) || width <= 0 || height <= 0) return null;
    return {
      bbox,
      frame: { width, height },
      label: String(detail.label || detail.targetDescription || "当前目标"),
      source: String(detail.source || "target-perception"),
      mock: Boolean(detail.mock),
      message: String(detail.message || ""),
    };
  }

  function containTransform(containerWidth, containerHeight, sourceWidth, sourceHeight) {
    const api = window.GongshuTargetSelection;
    if (api?.objectFitContainTransform) {
      return api.objectFitContainTransform(containerWidth, containerHeight, sourceWidth, sourceHeight);
    }
    const scale = Math.min(containerWidth / sourceWidth, containerHeight / sourceHeight);
    const renderedWidth = sourceWidth * scale;
    const renderedHeight = sourceHeight * scale;
    return {
      scale,
      renderedWidth,
      renderedHeight,
      offsetX: (containerWidth - renderedWidth) / 2,
      offsetY: (containerHeight - renderedHeight) / 2,
    };
  }

  function globalTargetRect(target) {
    const surfaceRect = liveStage?.getBoundingClientRect();
    if (!surfaceRect || surfaceRect.width < 1 || surfaceRect.height < 1) return null;
    const transform = containTransform(surfaceRect.width, surfaceRect.height, target.frame.width, target.frame.height);
    const [x1, y1, x2, y2] = target.bbox;
    return {
      x1: surfaceRect.left + transform.offsetX + x1 * transform.scale,
      y1: surfaceRect.top + transform.offsetY + y1 * transform.scale,
      x2: surfaceRect.left + transform.offsetX + x2 * transform.scale,
      y2: surfaceRect.top + transform.offsetY + y2 * transform.scale,
    };
  }

  function fits(candidate, width, height) {
    const viewport = viewportSize();
    return candidate.x >= 8
      && candidate.y >= 8
      && candidate.x + width <= viewport.width - 8
      && candidate.y + height <= viewport.height - 8;
  }

  function placementFor(target) {
    const box = globalTargetRect(target);
    if (!box) return null;
    const viewport = viewportSize();
    const { width, height } = actorSize();
    const margin = clamp(viewport.width * .012, 10, 20);
    const centerX = (box.x1 + box.x2) / 2;
    const centerY = (box.y1 + box.y2) / 2;
    const topFor = (value) => clamp(value, 8, Math.max(8, viewport.height - height - 8));
    const candidates = [
      { x: box.x1 - width - margin, y: topFor(centerY - height * .62), side: "left" },
      { x: box.x2 + margin, y: topFor(centerY - height * .62), side: "right" },
      { x: clamp(centerX - width / 2, 8, viewport.width - width - 8), y: box.y1 - height - margin, side: "above" },
      { x: clamp(centerX - width / 2, 8, viewport.width - width - 8), y: box.y2 + margin, side: "below" },
    ];
    const selected = candidates.find((candidate) => fits(candidate, width, height)) || {
      x: clamp(candidates[0].x, 8, viewport.width - width - 8),
      y: topFor(candidates[0].y),
      side: candidates[0].x < centerX ? "left" : "right",
    };
    const side = ["left", "right"].includes(selected.side)
      ? selected.side
      : selected.x < centerX ? "left" : "right";
    return {
      ...selected,
      side,
      facing: side === "left" ? "point-right" : "point-left",
      box,
      width,
      height,
    };
  }

  function renderMarker(target, placement) {
    if (!marker || !target.mock || !placement?.box) {
      marker?.setAttribute("hidden", "");
      return;
    }
    const box = placement.box;
    layer.style.setProperty("--target-x", `${box.x1}px`);
    layer.style.setProperty("--target-y", `${box.y1}px`);
    layer.style.setProperty("--target-width", `${Math.max(1, box.x2 - box.x1)}px`);
    layer.style.setProperty("--target-height", `${Math.max(1, box.y2 - box.y1)}px`);
    marker.removeAttribute("hidden");
  }

  function bubbleFor(target, placement) {
    if (target.message) return target.message;
    if (target.mock) return placement?.side === "right" ? "左侧目标已确认。" : "右侧目标已确认。";
    if (target.source === "vlm") return "找到了，就是这个。";
    return "已锁定当前目标。";
  }

  function showPet() {
    if (state.advisorMode) return false;
    layer.removeAttribute("hidden");
    actor.classList.add("is-visible");
    if (!state.homePosition) state.homePosition = readStoredHomePosition() || defaultHomePosition();
    if (!state.position) setPosition(state.homePosition);
    state.visible = true;
    return true;
  }

  function hidePet() {
    window.clearTimeout(state.transitionTimer);
    window.clearTimeout(state.dismissTimer);
    state.drag = null;
    state.target = null;
    state.placement = null;
    state.visible = false;
    marker?.setAttribute("hidden", "");
    setBubble("");
    actor.classList.remove("is-visible", "is-dragging");
    layer.setAttribute("hidden", "");
    setState("idle");
  }

  function updatePetAccessibility() {
    if (state.advisorMode) {
      layer.setAttribute("aria-label", "Gongshu Assistant overlay disabled in Advisor Mode");
      actor.setAttribute("aria-label", "Gongshu Assistant pet disabled in Advisor Mode");
      sprite.alt = "";
    } else {
      layer.setAttribute("aria-label", "云冈娘常驻桌面宠物 Yungang Pet");
      actor.setAttribute("aria-label", "云冈娘 Yungang Pet，可拖拽");
      sprite.alt = "云冈娘 Yungang Pet";
    }
  }

  function moveToPlacement(placement) {
    state.placement = placement;
    setState("move");
    setPosition(placement);
    window.clearTimeout(state.transitionTimer);
    state.transitionTimer = window.setTimeout(() => {
      if (state.target && state.placement === placement && !state.drag) setState(placement.facing);
    }, TRANSITION_MS);
  }

  function refreshTargetPlacement() {
    if (!state.target || state.drag) return;
    const placement = placementFor(state.target);
    if (!placement) return;
    state.placement = placement;
    renderMarker(state.target, placement);
    setPosition(placement);
  }

  function presentTarget(detail) {
    if (state.advisorMode) return;
    const target = normalizedTarget(detail);
    if (!target || !showPet()) return;
    state.target = target;
    const placement = placementFor(target);
    if (!placement) return;
    renderMarker(target, placement);
    setBubble(bubbleFor(target, placement));
    moveToPlacement(placement);
  }

  function clearTarget() {
    state.target = null;
    state.placement = null;
    window.clearTimeout(state.transitionTimer);
    marker?.setAttribute("hidden", "");
    setBubble("");
    if (state.advisorMode || !state.visible) return;
    setState("dismiss");
    setPosition(state.homePosition || defaultHomePosition());
    window.clearTimeout(state.dismissTimer);
    state.dismissTimer = window.setTimeout(() => {
      if (!state.target && state.visible && !state.drag) setState("idle");
    }, TRANSITION_MS);
  }

  function setAdvisorMode(enabled) {
    state.advisorMode = Boolean(enabled);
    toggle.checked = state.advisorMode;
    modeState.textContent = state.advisorMode ? "ON · FORMAL" : "OFF · YUNGANG PET";
    modeState.classList.toggle("is-off", !state.advisorMode);
    document.body.classList.toggle("advisor-mode", state.advisorMode);
    updatePetAccessibility();
    try {
      window.localStorage.setItem(ADVISOR_STORAGE_KEY, String(state.advisorMode));
    } catch {
      // The current page still follows the selected mode.
    }
    if (state.advisorMode) {
      hidePet();
    } else {
      showPet();
      setState("idle");
    }
    window.dispatchEvent(new CustomEvent("gongshu:advisor-mode-change", {
      detail: { advisorMode: state.advisorMode },
    }));
  }

  function setMockTarget(side = "right") {
    const isLeftTarget = side === "left";
    presentTarget({
      bbox: isLeftTarget ? [70, 250, 200, 410] : [710, 250, 840, 410],
      frame: DEFAULT_FRAME,
      label: isLeftTarget ? "左侧 mock 目标" : "右侧 mock 目标",
      source: "mock",
      mock: true,
      message: isLeftTarget ? "左侧目标已确认。" : "右侧目标已确认。",
    });
  }

  function beginDrag(event) {
    if (state.advisorMode || !state.visible || state.target || event.button !== 0) return;
    const rect = actor.getBoundingClientRect();
    state.drag = {
      pointerId: event.pointerId,
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
    };
    actor.setPointerCapture?.(event.pointerId);
    actor.classList.add("is-dragging");
    setState("dragging");
    event.preventDefault();
    event.stopPropagation();
  }

  function dragMove(event) {
    if (!state.drag || event.pointerId !== state.drag.pointerId) return;
    const rect = layer.getBoundingClientRect();
    setPosition({
      x: event.clientX - rect.left - state.drag.offsetX,
      y: event.clientY - rect.top - state.drag.offsetY,
    });
    event.preventDefault();
    event.stopPropagation();
  }

  function endDrag(event) {
    if (!state.drag || event.pointerId !== state.drag.pointerId) return;
    actor.releasePointerCapture?.(event.pointerId);
    state.drag = null;
    actor.classList.remove("is-dragging");
    state.homePosition = { ...state.position };
    saveHomePosition();
    setState("idle");
    event.preventDefault();
    event.stopPropagation();
  }

  actor.addEventListener("pointerdown", beginDrag);
  actor.addEventListener("pointermove", dragMove);
  actor.addEventListener("pointerup", endDrag);
  actor.addEventListener("pointercancel", endDrag);
  toggle.addEventListener("change", () => setAdvisorMode(toggle.checked));
  settingsButton?.addEventListener("click", () => {
    if (typeof settingsDialog?.showModal === "function") settingsDialog.showModal();
  });
  settingsDialog?.addEventListener("click", (event) => {
    if (event.target === settingsDialog || event.target.closest("[data-close-advisor-settings]")) {
      settingsDialog.close();
    }
  });
  window.addEventListener("gongshu:target-bbox", (event) => presentTarget(event.detail));
  window.addEventListener("gongshu:target-reset", clearTarget);
  window.addEventListener("resize", () => {
    if (state.target) refreshTargetPlacement();
    else restoreHomePosition();
  });
  window.addEventListener("scroll", () => {
    if (state.target) refreshTargetPlacement();
  }, { passive: true });
  if (typeof ResizeObserver === "function") {
    const observer = new ResizeObserver(() => {
      if (state.target) refreshTargetPlacement();
      else restoreHomePosition();
    });
    observer.observe(document.documentElement);
    if (liveStage) observer.observe(liveStage);
  }

  modeState.textContent = state.advisorMode ? "ON · FORMAL" : "OFF · YUNGANG PET";
  modeState.classList.toggle("is-off", !state.advisorMode);
  toggle.checked = state.advisorMode;
  document.body.classList.toggle("advisor-mode", state.advisorMode);
  updatePetAccessibility();
  window.GongshuAdvisorMode = Object.freeze({
    isAdvisorMode: () => state.advisorMode,
    setAdvisorMode,
  });
  window.GongshuYungangAssistant = Object.freeze({
    clearTarget,
    setMockTarget,
    setTarget: presentTarget,
  });
  window.requestAnimationFrame(() => {
    if (!state.advisorMode) {
      showPet();
      setState("idle");
    }
  });
})();
