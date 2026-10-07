(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const stage = byId("assistantStageLayer")?.parentElement;
  const layer = byId("assistantStageLayer");
  const actor = byId("yungangAssistantActor");
  const sprite = byId("yungangAssistantSprite");
  const bubble = byId("yungangAssistantBubble");
  const marker = byId("assistantTargetMarker");
  const toggle = byId("yungangDesktopAssistantToggle");
  const modeState = byId("yungangDesktopAssistantState");
  if (!stage || !layer || !actor || !sprite || !bubble || !toggle) return;

  const ASSET_BASE = "../../assets/yungang/";
  const SPRITES = Object.freeze({
    idle: `${ASSET_BASE}yungang_idle.png`,
    move: `${ASSET_BASE}yungang_move.png`,
    "point-left": `${ASSET_BASE}yungang_point_left.png`,
    "point-right": `${ASSET_BASE}yungang_point_right.png`,
  });
  const DEFAULT_FRAME = Object.freeze({ width: 1000, height: 650 });
  const TRANSITION_MS = 430;
  const state = {
    enabled: toggle.checked,
    target: null,
    placement: null,
    visible: false,
    transitionTimer: 0,
    dismissTimer: 0,
  };

  function finite(value) {
    return Number.isFinite(Number(value));
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), Math.max(min, max));
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

  function stageTargetRect(target, width, height) {
    const transform = containTransform(width, height, target.frame.width, target.frame.height);
    const [x1, y1, x2, y2] = target.bbox;
    return {
      x1: transform.offsetX + x1 * transform.scale,
      y1: transform.offsetY + y1 * transform.scale,
      x2: transform.offsetX + x2 * transform.scale,
      y2: transform.offsetY + y2 * transform.scale,
    };
  }

  function actorSize(stageWidth, stageHeight) {
    const cssWidth = actor.getBoundingClientRect().width;
    const width = cssWidth > 0 ? cssWidth : clamp(stageWidth * .16, 68, 142);
    return { width, height: Math.min(stageHeight - 16, width * 4 / 3) };
  }

  function fits(candidate, width, height) {
    return candidate.x >= 8
      && candidate.y >= 8
      && candidate.x + width <= stage.clientWidth - 8
      && candidate.y + height <= stage.clientHeight - 8;
  }

  function placementFor(target) {
    const stageWidth = stage.clientWidth;
    const stageHeight = stage.clientHeight;
    if (stageWidth < 1 || stageHeight < 1) return null;
    const { width, height } = actorSize(stageWidth, stageHeight);
    const box = stageTargetRect(target, stageWidth, stageHeight);
    const margin = clamp(stageWidth * .018, 10, 20);
    const centerY = (box.y1 + box.y2) / 2;
    const centerX = (box.x1 + box.x2) / 2;
    const topFor = (y) => clamp(y, 8, Math.max(8, stageHeight - height - 8));
    const leftCandidate = { x: box.x1 - width - margin, y: topFor(centerY - height * .62), side: "left" };
    const rightCandidate = { x: box.x2 + margin, y: topFor(centerY - height * .62), side: "right" };
    const aboveCandidate = { x: clamp(centerX - width / 2, 8, stageWidth - width - 8), y: box.y1 - height - margin, side: "above" };
    const belowCandidate = { x: clamp(centerX - width / 2, 8, stageWidth - width - 8), y: box.y2 + margin, side: "below" };
    const candidates = [leftCandidate, rightCandidate, aboveCandidate, belowCandidate];
    const selected = candidates.find((candidate) => fits(candidate, width, height)) || {
      x: clamp(leftCandidate.x, 8, stageWidth - width - 8),
      y: topFor(leftCandidate.y),
      side: leftCandidate.x < centerX ? "left" : "right",
    };
    const side = selected.side === "left" || selected.side === "right"
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

  function setState(nextState) {
    actor.dataset.state = nextState;
    sprite.src = SPRITES[nextState] || SPRITES.idle;
  }

  function setBubble(text) {
    bubble.textContent = text;
  }

  function bubbleFor(target, placement) {
    if (target.message) return target.message;
    if (target.mock) return placement?.side === "right" ? "左侧目标已确认。" : "右侧目标已确认。";
    if (target.source === "vlm") return "找到了，就是这个。";
    return "已锁定当前目标。";
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

  function applyPlacement(placement) {
    actor.style.left = `${placement.x}px`;
    actor.style.top = `${placement.y}px`;
  }

  function presentTarget(detail) {
    if (!state.enabled) return;
    const target = normalizedTarget(detail);
    if (!target) return;
    const placement = placementFor(target);
    if (!placement) {
      state.target = target;
      return;
    }
    window.clearTimeout(state.transitionTimer);
    window.clearTimeout(state.dismissTimer);
    const firstAppearance = !state.visible;
    state.target = target;
    state.placement = placement;
    layer.removeAttribute("hidden");
    renderMarker(target, placement);
    setBubble(bubbleFor(target, placement));
    if (firstAppearance) {
      const standbyY = Math.max(8, stage.clientHeight - placement.height - 8);
      actor.style.left = "8px";
      actor.style.top = `${standbyY}px`;
      setState("summon");
      actor.classList.add("is-visible");
      void actor.offsetWidth;
    } else {
      setState("move");
    }
    state.visible = true;
    window.requestAnimationFrame(() => applyPlacement(placement));
    state.transitionTimer = window.setTimeout(() => setState(placement.facing), TRANSITION_MS);
  }

  function clearTarget() {
    state.target = null;
    state.placement = null;
    window.clearTimeout(state.transitionTimer);
    if (!state.visible) {
      marker?.setAttribute("hidden", "");
      layer.setAttribute("hidden", "");
      return;
    }
    setBubble("");
    setState("dismiss");
    marker?.setAttribute("hidden", "");
    actor.style.left = "8px";
    actor.style.top = `${Math.max(8, stage.clientHeight - actor.getBoundingClientRect().height - 8)}px`;
    state.dismissTimer = window.setTimeout(() => {
      actor.classList.remove("is-visible");
      layer.setAttribute("hidden", "");
      setState("idle");
      state.visible = false;
    }, TRANSITION_MS);
  }

  function setEnabled(enabled) {
    state.enabled = Boolean(enabled);
    toggle.checked = state.enabled;
    modeState.textContent = state.enabled ? "ON · WORKSPACE" : "OFF · STATIC CARD";
    modeState.classList.toggle("is-off", !state.enabled);
    if (!state.enabled) {
      state.target = null;
      clearTarget();
      return;
    }
    if (state.target) presentTarget(state.target);
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

  toggle.addEventListener("change", () => setEnabled(toggle.checked));
  window.addEventListener("gongshu:target-bbox", (event) => presentTarget(event.detail));
  window.addEventListener("gongshu:target-reset", clearTarget);
  window.addEventListener("resize", () => {
    if (state.enabled && state.target) presentTarget(state.target);
  });
  if (typeof ResizeObserver === "function") {
    new ResizeObserver(() => {
      if (state.enabled && state.target) presentTarget(state.target);
    }).observe(stage);
  }

  modeState.textContent = state.enabled ? "ON · WORKSPACE" : "OFF · STATIC CARD";
  window.GongshuYungangAssistant = Object.freeze({
    clearTarget,
    setEnabled,
    setMockTarget,
    setTarget: presentTarget,
  });
})();
