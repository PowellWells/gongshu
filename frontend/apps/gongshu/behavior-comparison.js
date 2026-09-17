(() => {
  "use strict";

  const openButton = document.querySelector("#xiezhiBehaviorComparisonOpen");
  const closeButton = document.querySelector("#xiezhiBehaviorComparisonClose");
  const dialog = document.querySelector("#xiezhiBehaviorComparisonDialog");
  const sceneLabel = document.querySelector("#xiezhiBehaviorComparisonScene");
  const differenceLabel = document.querySelector("#xiezhiTrajectoryDifference");
  let refreshTimer = 0;

  if (!openButton || !closeButton || !dialog) return;

  async function api(url) {
    const response = await fetch(url, { cache: "no-store" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.status === "error") {
      throw new Error(payload.message || `HTTP ${response.status}`);
    }
    return payload;
  }

  function setText(id, value) {
    const element = document.querySelector(id);
    if (element) element.textContent = value ?? "—";
  }

  function positionText(pose) {
    const position = pose?.position || [];
    if (position.length !== 3) return "—";
    return position.map((value) => Number(value).toFixed(3)).join(", ");
  }

  function sharedProjection(left, right) {
    const records = [left, right];
    const positions = records.flatMap((record) => (
      record?.trajectory_points || []
    ).map((point) => point.position_world));
    if (!positions.length) return null;
    const xs = positions.map((point) => Number(point[0]));
    const zs = positions.map((point) => Number(point[2]));
    let minX = Math.min(...xs);
    let maxX = Math.max(...xs);
    let minZ = Math.min(...zs);
    let maxZ = Math.max(...zs);
    if (maxX - minX < 0.01) {
      minX -= 0.005;
      maxX += 0.005;
    }
    if (maxZ - minZ < 0.01) {
      minZ -= 0.005;
      maxZ += 0.005;
    }
    return (position) => ({
      x: 30 + ((Number(position[0]) - minX) / (maxX - minX)) * 360,
      y: 220 - ((Number(position[2]) - minZ) / (maxZ - minZ)) * 180,
    });
  }

  function renderTrajectory(side, record, project) {
    const prefix = side === "left" ? "Left" : "Right";
    const trajectory = document.querySelector(`#behavior${prefix}Trajectory`);
    const start = document.querySelector(`#behavior${prefix}Start`);
    const end = document.querySelector(`#behavior${prefix}End`);
    const points = record?.trajectory_points || [];
    if (!trajectory || !start || !end || !project || !points.length) {
      if (trajectory) trajectory.setAttribute("points", "");
      return;
    }
    const projected = points.map((point) => project(point.position_world));
    trajectory.setAttribute(
      "points",
      projected.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" "),
    );
    const first = projected[0];
    const last = projected[projected.length - 1];
    start.setAttribute("cx", first.x.toFixed(1));
    start.setAttribute("cy", first.y.toFixed(1));
    end.setAttribute("cx", last.x.toFixed(1));
    end.setAttribute("cy", last.y.toFixed(1));
  }

  function renderSide(side, record, project) {
    const prefix = side === "left" ? "Left" : "Right";
    const validation = record?.validation_result || {};
    const trajectory = record?.trajectory_points || [];
    const actualEnd = trajectory.length
      ? { position: trajectory[trajectory.length - 1].position_world }
      : null;
    setText(
      `#behavior${prefix}Algorithm`,
      record ? `${record.algorithm_name} · ${record.algorithm_version}` : "等待记录 WAITING",
    );
    setText(`#behavior${prefix}Candidate`, record?.selected_candidate_id || "—");
    setText(
      `#behavior${prefix}Validation`,
      validation.validation_result || validation.state || "—",
    );
    setText(
      `#behavior${prefix}Time`,
      record ? `${Number(record.execution_time).toFixed(3)} s` : "—",
    );
    setText(
      `#behavior${prefix}StartPose`,
      `起点 START · ${positionText(record?.start_pose)}`,
    );
    setText(`#behavior${prefix}Endpoint`, `终点 END · ${positionText(actualEnd)}`);
    renderTrajectory(side, record, project);
  }

  function renderComparison(state) {
    if (state.schema_version !== "gongshu.behavior-comparison/v1") {
      throw new Error("unsupported Behavior Comparison schema");
    }
    const ready = state.status === "READY" && state.left && state.right;
    const project = ready ? sharedProjection(state.left, state.right) : null;
    renderSide("left", state.left, project);
    renderSide("right", state.right, project);
    sceneLabel.textContent = ready
      ? `同一场景 Same Scene · ${state.scene_id} · ${state.target_id}`
      : `等待同场景双算法记录 Waiting · ${state.record_count || 0}/2`;
    if (!ready) {
      differenceLabel.textContent = "先分别运行两个算法完成 MuJoCo 验证 RUN BOTH ALGORITHMS";
      return;
    }
    const difference = state.trajectory_difference || {};
    differenceLabel.textContent = [
      `终点距离 Endpoint Δ ${Number(difference.endpoint_distance_m || 0).toFixed(3)} m`,
      `路径长度差 Path Δ ${Number(difference.path_length_difference_m || 0).toFixed(3)} m`,
      difference.selected_candidate_changed ? "候选不同 DIFFERENT CANDIDATES" : "候选相同 SAME CANDIDATE",
    ].join(" · ");
  }

  async function refresh() {
    try {
      renderComparison(await api("/api/behavior-comparison"));
    } catch (error) {
      differenceLabel.textContent = `行为记录不可用 RECORDS UNAVAILABLE · ${error.message}`;
    }
  }

  openButton.addEventListener("click", () => {
    dialog.showModal();
    refresh();
    window.clearInterval(refreshTimer);
    refreshTimer = window.setInterval(refresh, 1500);
  });

  closeButton.addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => {
    window.clearInterval(refreshTimer);
    refreshTimer = 0;
  });
})();
