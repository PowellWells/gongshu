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
    run_a: `${ASSET_BASE}yungang_run_a.png`,
    run_b: `${ASSET_BASE}yungang_run_b.png`,
    brake: `${ASSET_BASE}yungang_brake.png`,
    thinking: `${ASSET_BASE}yungang_thinking.png`,
    success: `${ASSET_BASE}yungang_success.png`,
    warning: `${ASSET_BASE}yungang_warning.png`,
    failure: `${ASSET_BASE}yungang_failure.png`,
    "point-left": `${ASSET_BASE}yungang_point_left.png`,
    "point-right": `${ASSET_BASE}yungang_point_right.png`,
  });
  const SPRITE_FALLBACKS = Object.freeze({
    run_a: "move",
    run_b: "move",
    brake: "idle",
    thinking: "idle",
    success: "idle",
    warning: "idle",
    failure: "idle",
  });
  const DEFAULT_FRAME = Object.freeze({ width: 1000, height: 650 });
  const TRANSITION_MS = 430;
  const RUN_FRAME_MS = 135;
  const BRAKE_MS = 260;
  const OUTCOME_HOLD_MS = 2800;
  const RUNTIME_STATE = Object.freeze({
    IDLE: "IDLE",
    DRAGGING: "DRAGGING",
    MOVING: "MOVING",
    POINTING: "POINTING",
    THINKING: "THINKING",
    EXECUTING: "EXECUTING",
    SUCCESS: "SUCCESS",
    WARNING: "WARNING",
    FAILURE: "FAILURE",
    RETURN_HOME: "RETURN_HOME",
    BRAKING: "BRAKING",
  });
  const FAILURE_STATE = Object.freeze({
    approach_collision: RUNTIME_STATE.WARNING,
    miss_or_empty_closure: RUNTIME_STATE.FAILURE,
    slip_or_drop: RUNTIME_STATE.FAILURE,
    insufficient_contact: RUNTIME_STATE.WARNING,
    unstable_grasp: RUNTIME_STATE.WARNING,
    execution_timeout: RUNTIME_STATE.FAILURE,
    unknown_failure: RUNTIME_STATE.FAILURE,
  });
  const FAILURE_BUBBLES = Object.freeze({
    approach_collision: "接近路径发生碰撞，先换个方案。",
    miss_or_empty_closure: "这次抓空了，我看看接触位置。",
    slip_or_drop: "没有抓稳，目标发生了滑移。",
    insufficient_contact: "当前接触不足，建议换一个候选。",
    unstable_grasp: "这个抓取不够稳定。",
    execution_timeout: "执行等待超时，动作已经安全停止。",
    unknown_failure: "这次没有成功，执行证据已经记录。",
  });
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
    outcomeTimer: 0,
    returnTimer: 0,
    brakeTimer: 0,
    runFrameTimer: 0,
    runFrame: 0,
    runtimeState: RUNTIME_STATE.IDLE,
    handledEventIds: new Set(),
    unavailableSprites: new Set(),
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

  function spriteFallback(stateName) {
    return SPRITE_FALLBACKS[stateName] || "idle";
  }

  function applySprite(stateName) {
    const requested = SPRITES[stateName] ? stateName : "idle";
    const fallback = spriteFallback(requested);
    sprite.dataset.spriteState = requested;
    sprite.src = state.unavailableSprites.has(requested)
      ? SPRITES[fallback]
      : SPRITES[requested];
  }

  sprite.addEventListener("error", () => {
    const requested = sprite.dataset.spriteState;
    if (!requested || state.unavailableSprites.has(requested)) return;
    state.unavailableSprites.add(requested);
    applySprite(spriteFallback(requested));
  });

  function stopRunLoop() {
    window.clearInterval(state.runFrameTimer);
    state.runFrameTimer = 0;
    actor.classList.remove("assistant-running");
  }

  function startRunLoop() {
    stopRunLoop();
    state.runFrame = 0;
    actor.classList.add("assistant-running");
    applySprite("run_a");
    state.runFrameTimer = window.setInterval(() => {
      if (state.advisorMode || !state.visible || !state.drag && ![RUNTIME_STATE.MOVING, RUNTIME_STATE.RETURN_HOME].includes(state.runtimeState)) {
        stopRunLoop();
        return;
      }
      state.runFrame = state.runFrame ? 0 : 1;
      applySprite(state.runFrame ? "run_b" : "run_a");
    }, RUN_FRAME_MS);
  }

  function setState(nextState, runtimeState = null) {
    const classes = [
      "assistant-idle",
      "assistant-dragging",
      "assistant-moving",
      "assistant-pointing",
      "assistant-returning",
      "assistant-thinking",
      "assistant-executing",
      "assistant-success",
      "assistant-warning",
      "assistant-failure",
      "assistant-braking",
    ];
    actor.dataset.state = nextState;
    if (runtimeState) state.runtimeState = runtimeState;
    actor.dataset.runtimeState = state.runtimeState;
    actor.classList.remove(...classes);
    if (nextState === "idle") actor.classList.add("assistant-idle");
    if (nextState === "dragging") actor.classList.add("assistant-dragging");
    if (["summon", "move"].includes(nextState)) actor.classList.add("assistant-moving");
    if (["point-left", "point-right"].includes(nextState)) actor.classList.add("assistant-pointing");
    if (nextState === "dismiss") actor.classList.add("assistant-returning");
    if (nextState === "thinking") actor.classList.add("assistant-thinking");
    if (nextState === "executing") actor.classList.add("assistant-executing");
    if (nextState === "success") actor.classList.add("assistant-success");
    if (nextState === "warning") actor.classList.add("assistant-warning");
    if (nextState === "failure") actor.classList.add("assistant-failure");
    if (nextState === "brake") actor.classList.add("assistant-braking");
    applySprite(nextState);
  }

  function setRuntimeState(runtimeState, visualState = null) {
    if (state.advisorMode) return;
    if (![RUNTIME_STATE.DRAGGING, RUNTIME_STATE.MOVING, RUNTIME_STATE.RETURN_HOME].includes(runtimeState)) {
      stopRunLoop();
    }
    const visualByRuntime = {
      [RUNTIME_STATE.IDLE]: "idle",
      [RUNTIME_STATE.DRAGGING]: "dragging",
      [RUNTIME_STATE.MOVING]: "move",
      [RUNTIME_STATE.POINTING]: state.placement?.facing || "point-right",
      [RUNTIME_STATE.THINKING]: "thinking",
      [RUNTIME_STATE.EXECUTING]: "executing",
      [RUNTIME_STATE.SUCCESS]: "success",
      [RUNTIME_STATE.WARNING]: "warning",
      [RUNTIME_STATE.FAILURE]: "failure",
      [RUNTIME_STATE.RETURN_HOME]: "dismiss",
      [RUNTIME_STATE.BRAKING]: "brake",
    };
    setState(visualState || visualByRuntime[runtimeState] || "idle", runtimeState);
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

  function clearRuntimeTimers() {
    window.clearTimeout(state.transitionTimer);
    window.clearTimeout(state.dismissTimer);
    window.clearTimeout(state.outcomeTimer);
    window.clearTimeout(state.returnTimer);
    window.clearTimeout(state.brakeTimer);
    stopRunLoop();
  }

  function brakeThen(nextRuntimeState, nextVisualState = null) {
    if (state.advisorMode || !state.visible) return;
    window.clearTimeout(state.brakeTimer);
    stopRunLoop();
    setRuntimeState(RUNTIME_STATE.BRAKING, "brake");
    state.brakeTimer = window.setTimeout(() => {
      if (!state.advisorMode && state.visible && !state.drag) {
        setRuntimeState(nextRuntimeState, nextVisualState);
      }
    }, BRAKE_MS);
  }

  function returnHome() {
    if (state.advisorMode || !state.visible) return;
    clearRuntimeTimers();
    state.target = null;
    state.placement = null;
    marker?.setAttribute("hidden", "");
    setBubble("");
    setRuntimeState(RUNTIME_STATE.RETURN_HOME);
    setPosition(state.homePosition || defaultHomePosition());
    state.returnTimer = window.setTimeout(() => {
      if (!state.drag && !state.advisorMode) brakeThen(RUNTIME_STATE.IDLE, "idle");
    }, TRANSITION_MS);
    startRunLoop();
  }

  function presentOutcome(runtimeState, message, eventId) {
    if (state.advisorMode || !showPet()) return;
    if (eventId && state.handledEventIds.has(eventId)) return;
    if (eventId) {
      state.handledEventIds.add(eventId);
      if (state.handledEventIds.size > 128) {
        state.handledEventIds.delete(state.handledEventIds.values().next().value);
      }
    }
    clearRuntimeTimers();
    setBubble(message);
    setRuntimeState(runtimeState);
    state.outcomeTimer = window.setTimeout(returnHome, OUTCOME_HOLD_MS);
  }

  function handleExecutionEvent(event) {
    if (state.advisorMode || !event) return;
    const eventId = String(event.event_id || event.message_id || "").trim();
    if (!eventId || state.handledEventIds.has(eventId)) return;
    const metadata = event.metadata && typeof event.metadata === "object" ? event.metadata : {};
    if (event.message_type === "system_error") {
      presentOutcome(RUNTIME_STATE.WARNING, "执行遇到异常，动作已经安全停止。", eventId);
      return;
    }
    if (event.message_type !== "grasp_feedback") return;
    if (metadata.success === true) {
      presentOutcome(RUNTIME_STATE.SUCCESS, "抓到了，目标已经稳定抬升。", eventId);
      return;
    }
    if (metadata.success !== false) return;
    const failureType = String(metadata.failure_type || "unknown_failure");
    presentOutcome(
      FAILURE_STATE[failureType] || RUNTIME_STATE.FAILURE,
      FAILURE_BUBBLES[failureType] || FAILURE_BUBBLES.unknown_failure,
      eventId,
    );
  }

  function handlePipelineState(detail = {}) {
    if (state.advisorMode || !state.visible || !state.target) return;
    const pipelineState = String(detail.state || "").toUpperCase();
    if (["SCENE_CAPTURED", "SPATIAL_ANALYSIS", "SPATIAL_READY", "GRASP_PLANNING"].includes(pipelineState)) {
      setRuntimeState(RUNTIME_STATE.THINKING);
    } else if (["SCENE_SYNC", "SIMULATION"].includes(pipelineState)) {
      setRuntimeState(RUNTIME_STATE.EXECUTING);
    }
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
    clearRuntimeTimers();
    state.drag = null;
    state.target = null;
    state.placement = null;
    state.visible = false;
    marker?.setAttribute("hidden", "");
    setBubble("");
    actor.classList.remove("is-visible", "is-dragging");
    layer.setAttribute("hidden", "");
    state.runtimeState = RUNTIME_STATE.IDLE;
    setState("idle", RUNTIME_STATE.IDLE);
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
    setRuntimeState(RUNTIME_STATE.MOVING, "move");
    setPosition(placement);
    startRunLoop();
    window.clearTimeout(state.transitionTimer);
    state.transitionTimer = window.setTimeout(() => {
      if (state.target && state.placement === placement && !state.drag) {
        brakeThen(RUNTIME_STATE.POINTING, placement.facing);
      }
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
    clearRuntimeTimers();
    state.target = target;
    const placement = placementFor(target);
    if (!placement) return;
    renderMarker(target, placement);
    setBubble(bubbleFor(target, placement));
    moveToPlacement(placement);
  }

  function clearTarget() {
    clearRuntimeTimers();
    if (state.advisorMode || !state.visible) return;
    returnHome();
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
      setRuntimeState(RUNTIME_STATE.IDLE);
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
    setRuntimeState(RUNTIME_STATE.DRAGGING, "dragging");
    startRunLoop();
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
    brakeThen(RUNTIME_STATE.IDLE, "idle");
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
  window.addEventListener("gongshu:chat-event", (event) => handleExecutionEvent(event.detail));
  window.addEventListener("gongshu:pipeline-state", (event) => handlePipelineState(event.detail));
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
  actor.dataset.runtimeState = RUNTIME_STATE.IDLE;
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
      setRuntimeState(RUNTIME_STATE.IDLE);
    }
  });
})();
