(function pipelineStateModule(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.GongshuPipeline = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function createPipelineStateApi() {
  "use strict";

  const STATES = Object.freeze([
    "LIVE",
    "TARGET_SELECTED",
    "SCENE_CAPTURED",
    "SPATIAL_ANALYSIS",
    "SPATIAL_READY",
    "GRASP_PLANNING",
    "SCENE_SYNC",
    "SIMULATION",
    "VERIFIED",
    "RESET",
  ]);

  const VIEW_BY_STATE = Object.freeze({
    LIVE: "live",
    TARGET_SELECTED: "live",
    SCENE_CAPTURED: "live",
    SPATIAL_ANALYSIS: "spatial",
    SPATIAL_READY: "spatial",
    GRASP_PLANNING: "grasp",
    SCENE_SYNC: "grasp",
    SIMULATION: "simulation",
    VERIFIED: "simulation",
    RESET: "live",
  });

  const NEXT_STATES = Object.freeze({
    LIVE: new Set(["TARGET_SELECTED", "RESET"]),
    TARGET_SELECTED: new Set(["SCENE_CAPTURED", "RESET"]),
    SCENE_CAPTURED: new Set(["SPATIAL_ANALYSIS", "RESET"]),
    SPATIAL_ANALYSIS: new Set(["SPATIAL_READY", "GRASP_PLANNING", "RESET"]),
    SPATIAL_READY: new Set(["GRASP_PLANNING", "RESET"]),
    GRASP_PLANNING: new Set(["SCENE_SYNC", "RESET"]),
    SCENE_SYNC: new Set(["SIMULATION", "RESET"]),
    SIMULATION: new Set(["VERIFIED", "RESET"]),
    VERIFIED: new Set(["RESET"]),
    RESET: new Set(["LIVE"]),
  });

  class PipelineStateMachine {
    constructor(initialState = "LIVE") {
      if (!STATES.includes(initialState)) throw new Error(`Unknown pipeline state: ${initialState}`);
      this.state = initialState;
      this.revision = 0;
      this.listeners = new Set();
      this.history = [{ state: initialState, revision: 0, detail: { reason: "initial" } }];
    }

    canTransition(nextState) {
      return STATES.includes(nextState) && NEXT_STATES[this.state].has(nextState);
    }

    transition(nextState, detail = {}) {
      if (!this.canTransition(nextState)) {
        throw new Error(`Invalid pipeline transition: ${this.state} -> ${nextState}`);
      }
      const previousState = this.state;
      this.state = nextState;
      this.revision += 1;
      const event = Object.freeze({
        state: nextState,
        previousState,
        revision: this.revision,
        detail: Object.freeze({ ...detail }),
        primaryView: VIEW_BY_STATE[nextState],
      });
      this.history.push(event);
      this.listeners.forEach((listener) => listener(event));
      return event;
    }

    reset(detail = {}) {
      if (this.state !== "RESET") this.transition("RESET", detail);
      return this.transition("LIVE", { ...detail, reason: detail.reason || "reset-complete" });
    }

    subscribe(listener) {
      if (typeof listener !== "function") throw new TypeError("Pipeline listener must be a function");
      this.listeners.add(listener);
      return () => this.listeners.delete(listener);
    }

    primaryView() {
      return VIEW_BY_STATE[this.state];
    }
  }

  function hasTargetSnapshotAssociation(targetState) {
    const frame = targetState?.frame;
    const target = targetState?.selected_target;
    const snapshot = targetState?.scene_snapshot;
    return targetState?.status === "TARGET_LOCKED"
      && Boolean(frame && target && snapshot?.available && snapshot.snapshot_id)
      && target.id === targetState.selected_target_id
      && target.source_frame_id === frame.id
      && snapshot.source_frame_id === frame.id
      && snapshot.target_id === target.id
      && target.source_timestamp_s === frame.timestamp_s
      && snapshot.source_timestamp_s === frame.timestamp_s;
  }

  function canStartGrasp(pipelineState, targetState) {
    return pipelineState === "TARGET_SELECTED" && hasTargetSnapshotAssociation(targetState);
  }

  function hasSpatialObservationAssociation(targetState, spatialState) {
    const snapshot = targetState?.scene_snapshot;
    const observation = spatialState?.observation;
    return spatialState?.status === "READY"
      && Boolean(snapshot?.available && observation)
      && observation.snapshot_id === snapshot.snapshot_id
      && Boolean(snapshot.geometry_chain_id)
      && observation.geometry_chain_id === snapshot.geometry_chain_id
      && observation.source_frame_id === snapshot.source_frame_id
      && observation.target_instance_id === snapshot.target_id
      && observation.source_timestamp_s === snapshot.source_timestamp_s;
  }

  function hasGraspPlanAssociation(spatialState, graspState) {
    const observation = spatialState?.observation;
    const plan = graspState?.plan;
    return graspState?.status === "READY"
      && Boolean(observation && plan)
      && plan.planning_state === "READY"
      && plan.snapshot_id === observation.snapshot_id
      && plan.source_frame_id === observation.source_frame_id
      && plan.target_id === observation.target_instance_id;
  }

  return Object.freeze({
    STATES,
    VIEW_BY_STATE,
    NEXT_STATES,
    PipelineStateMachine,
    hasTargetSnapshotAssociation,
    hasSpatialObservationAssociation,
    hasGraspPlanAssociation,
    canStartGrasp,
  });
});
