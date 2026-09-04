(function targetSelectionModule(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.GongshuTargetSelection = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function createTargetSelectionApi() {
  "use strict";

  function finitePositive(value) {
    return Number.isFinite(Number(value)) && Number(value) > 0;
  }

  function objectFitContainTransform(containerWidth, containerHeight, sourceWidth, sourceHeight) {
    if (![containerWidth, containerHeight, sourceWidth, sourceHeight].every(finitePositive)) {
      throw new TypeError("contain geometry requires positive finite dimensions");
    }
    const scale = Math.min(containerWidth / sourceWidth, containerHeight / sourceHeight);
    const renderedWidth = sourceWidth * scale;
    const renderedHeight = sourceHeight * scale;
    return Object.freeze({
      scale,
      renderedWidth,
      renderedHeight,
      offsetX: (containerWidth - renderedWidth) / 2,
      offsetY: (containerHeight - renderedHeight) / 2,
    });
  }

  function clientPointToSource(point, elementRect, frame) {
    const transform = objectFitContainTransform(
      elementRect.width,
      elementRect.height,
      frame.width,
      frame.height,
    );
    const localX = Number(point.clientX) - Number(elementRect.left) - transform.offsetX;
    const localY = Number(point.clientY) - Number(elementRect.top) - transform.offsetY;
    if (
      !Number.isFinite(localX)
      || !Number.isFinite(localY)
      || localX < 0
      || localY < 0
      || localX >= transform.renderedWidth
      || localY >= transform.renderedHeight
    ) {
      return null;
    }
    return Object.freeze({
      x: localX / transform.scale,
      y: localY / transform.scale,
    });
  }

  function canSelectFrozenTarget(pipelineState, targetState) {
    return ["LIVE", "TARGET_SELECTED"].includes(pipelineState)
      && ["CANDIDATES", "TARGET_LOCKED"].includes(targetState?.status)
      && Boolean(targetState?.frame)
      && Array.isArray(targetState?.candidates)
      && targetState.candidates.length > 0;
  }

  return Object.freeze({
    objectFitContainTransform,
    clientPointToSource,
    canSelectFrozenTarget,
  });
});
