(() => {
  "use strict";

  const entry = document.querySelector('[data-xiezhi-entry="blueprint"]');
  const dialog = document.querySelector("#xiezhiBlueprintDialog");
  const closeButton = document.querySelector("#xiezhiBlueprintClose");
  const pipeline = document.querySelector("#xiezhiBlueprintPipeline");
  let dashboardState = null;
  let selectedStageId = null;
  let renderedBlueprint = null;

  if (!entry || !dialog || !pipeline) return;

  function setText(selector, value) {
    const element = document.querySelector(selector);
    if (element) element.textContent = value || "—";
  }

  function orderedStages(blueprint) {
    const stages = Array.isArray(blueprint?.stages) ? blueprint.stages : [];
    const stageById = new Map(stages.map((stage) => [stage.stage_id, stage]));
    const outgoing = new Map(stages.map((stage) => [stage.stage_id, []]));
    const incoming = new Map(stages.map((stage) => [stage.stage_id, 0]));
    (blueprint?.edges || []).forEach(([source, target]) => {
      if (!stageById.has(source) || !stageById.has(target)) return;
      outgoing.get(source).push(target);
      incoming.set(target, incoming.get(target) + 1);
    });
    const queue = stages.filter((stage) => incoming.get(stage.stage_id) === 0);
    const ordered = [];
    while (queue.length) {
      const stage = queue.shift();
      ordered.push(stage);
      outgoing.get(stage.stage_id).forEach((target) => {
        incoming.set(target, incoming.get(target) - 1);
        if (incoming.get(target) === 0) queue.push(stageById.get(target));
      });
    }
    return ordered.length === stages.length ? ordered : stages;
  }

  function selectStage(stage, button) {
    selectedStageId = stage.stage_id;
    [...pipeline.querySelectorAll(".xiezhi-blueprint-node")].forEach((node) => {
      const selected = node === button;
      node.classList.toggle("is-selected", selected);
      node.setAttribute("aria-selected", String(selected));
    });
    setText("#xiezhiBlueprintNodeName", stage.name);
    setText("#xiezhiBlueprintNodeDescription", stage.description);
    setText("#xiezhiBlueprintNodeModule", stage.module);
    setText("#xiezhiBlueprintNodeFunction", stage.function);
    setText("#xiezhiBlueprintNodeInput", stage.input_contract);
    setText("#xiezhiBlueprintNodeOutput", stage.output_contract);
  }

  function renderBlueprint(state) {
    const engine = state?.engine || {};
    const metadata = engine.algorithm_metadata || {};
    const blueprint = engine.blueprint;
    const stages = orderedStages(blueprint);
    pipeline.replaceChildren();
    if (!blueprint || !stages.length) return false;
    renderedBlueprint = JSON.stringify(blueprint);

    setText("#xiezhiBlueprintTitle", `${metadata.name || "Algorithm"} ${engine.algorithm_version || ""}`.trim());
    setText("#xiezhiBlueprintIdentity", `${engine.algorithm_type || "—"} · ${engine.algorithm_status || "—"}`);
    setText("#xiezhiBlueprintSchema", blueprint.schema_version);
    setText("#xiezhiBlueprintId", blueprint.blueprint_id);

    let stageToSelect = stages.find((stage) => stage.stage_id === selectedStageId) || stages[0];
    let buttonToSelect = null;
    stages.forEach((stage, index) => {
      if (index) {
        const edge = document.createElement("i");
        edge.className = "xiezhi-blueprint-edge";
        edge.setAttribute("aria-hidden", "true");
        pipeline.append(edge);
      }
      const button = document.createElement("button");
      button.type = "button";
      button.className = "xiezhi-blueprint-node";
      button.dataset.blueprintStage = stage.stage_id;
      button.setAttribute("role", "listitem");
      button.setAttribute("aria-selected", "false");

      const sequence = document.createElement("small");
      sequence.textContent = String(index + 1).padStart(2, "0");
      const name = document.createElement("strong");
      name.textContent = stage.name;
      const contract = document.createElement("span");
      contract.textContent = `${stage.input_contract} → ${stage.output_contract}`;
      button.append(sequence, name, contract);
      button.addEventListener("click", () => selectStage(stage, button));
      pipeline.append(button);
      if (stage === stageToSelect) buttonToSelect = button;
    });
    selectStage(stageToSelect, buttonToSelect);
    return true;
  }

  window.addEventListener("xiezhi:dashboard-state", (event) => {
    dashboardState = event.detail;
    const blueprint = dashboardState?.engine?.blueprint;
    entry.disabled = !blueprint;
    if (!blueprint) {
      entry.querySelector("span").textContent = "等待数据 WAITING";
      if (dialog.open) dialog.close();
      return;
    }
    entry.querySelector("span").textContent = dashboardState.engine.blueprint_reference;
    if (dialog.open && renderedBlueprint !== JSON.stringify(blueprint)) {
      renderBlueprint(dashboardState);
    }
  });

  entry.addEventListener("click", () => {
    if (!renderBlueprint(dashboardState)) return;
    dialog.showModal();
  });
  closeButton?.addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
})();
