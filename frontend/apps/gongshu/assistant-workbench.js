(() => {
  const byId = (id) => document.getElementById(id);
  const tabs = [...document.querySelectorAll("[data-workspace-tab]")];
  const messages = byId("assistantMessages");
  const input = byId("vlmInstruction");
  const groundButton = byId("vlmGroundButton");
  const diagnostics = byId("xiezhiLab");
  const diagnosticsToggle = byId("expertDiagnosticsToggle");
  let lastGroundingMessage = "";

  function addMessage(kind, author, text) {
    if (!messages || !text) return;
    const message = document.createElement("article");
    message.className = `assistant-message is-${kind}`;
    const label = document.createElement("span");
    label.className = "message-author";
    label.textContent = author;
    const copy = document.createElement("p");
    copy.textContent = text;
    message.append(label, copy);
    messages.append(message);
    messages.scrollTop = messages.scrollHeight;
  }

  function activeView() {
    const primary = document.querySelector(".workspace-view.is-primary");
    return primary?.dataset.view || "live";
  }

  function syncTabs() {
    const view = activeView();
    tabs.forEach((tab) => {
      const tabView = tab.dataset.workspaceTab === "spatial-depth" ? "spatial" : tab.dataset.workspaceTab;
      tab.classList.toggle("is-active", tabView === view);
    });
  }

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const view = tab.dataset.workspaceTab === "spatial-depth" ? "spatial" : tab.dataset.workspaceTab;
      const pinButton = document.querySelector(`[data-pin-view="${view}"]`);
      if (pinButton) pinButton.click();
      window.setTimeout(syncTabs, 0);
    });
  });

  document.querySelectorAll("[data-assistant-command]").forEach((button) => {
    button.addEventListener("click", () => {
      const command = button.dataset.assistantCommand || "";
      if (command === "重新观察") {
        addMessage("user", "你", command);
        window.GongshuYungangAssistant?.clearTarget();
        const scanButton = byId("analyzeTargetsButton");
        if (scanButton && !scanButton.disabled) scanButton.click();
        else addMessage("assistant", "云冈娘", "当前还不能重新观察，请先连接视觉输入。");
        return;
      }
      if (command === "执行当前抓取") {
        addMessage("user", "你", command);
        const graspButton = byId("startGraspButton");
        if (graspButton && !graspButton.disabled) graspButton.click();
        else addMessage("assistant", "云冈娘", "当前还没有可执行的抓取计划。");
        return;
      }
      if ((command === "抓左边那个" || command === "抓右边那个")
        && groundButton?.disabled
        && window.GongshuYungangAssistant?.setMockTarget) {
        addMessage("user", "你", command);
        window.GongshuYungangAssistant.setMockTarget(command === "抓左边那个" ? "left" : "right");
        addMessage("assistant", "云冈娘", command === "抓左边那个" ? "左侧目标已确认。" : "右侧目标已确认。");
        return;
      }
      if (!input) return;
      input.value = command;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      if (groundButton && !groundButton.disabled) groundButton.click();
    });
  });

  if (groundButton) {
    groundButton.addEventListener("click", () => {
      const command = input?.value.trim();
      if (command) addMessage("user", "你", command);
      if (command) addMessage("assistant", "云冈娘", "收到，我正在让本地视觉模型定位目标。");
    });
  }

  if (diagnosticsToggle && diagnostics) {
    diagnosticsToggle.addEventListener("click", () => {
      const collapsed = diagnostics.classList.toggle("is-collapsed");
      diagnosticsToggle.setAttribute("aria-expanded", String(!collapsed));
      diagnosticsToggle.textContent = collapsed
        ? "专家诊断 EXPERT DIAGNOSTICS"
        : "收起诊断 COLLAPSE DIAGNOSTICS";
    });
  }

  function text(id, fallback = "—") {
    return byId(id)?.textContent?.trim() || fallback;
  }

  function updateSummary() {
    const instruction = text("vlmInstructionEcho", "等待自然语言指令");
    const target = text("vlmTargetValue", "等待目标");
    const mask = text("vlmMaskValue", "等待目标锁定 WAITING");
    const spatial = text("spatialInspectorStatus", "WAITING");
    const grasp = text("graspInspectorStatus", "WAITING");
    const xiezhi = text("xiezhiRuntimeContext", "后台决策模块");
    const mujoco = text("simulationState", "WAITING");
    const values = {
      summaryTask: instruction,
      summaryGrounding: target,
      summaryMask: mask,
      summarySpatial: text("spatialValue", "Depth / Point Cloud"),
      summaryGrasp: text("graspValue", "候选等待中"),
      summaryXiezhi: xiezhi,
      summaryMujoco: text("simulationTarget", mujoco),
      summaryTaskState: instruction === "等待自然语言指令" ? "WAITING" : "RECEIVED",
      summaryGroundingState: target === "等待定位 WAITING" ? "WAITING" : text("vlmGroundingStatus", "GROUNDED"),
      summaryMaskState: mask.includes("READY") || mask.includes("LOCKED") ? "READY" : "WAITING",
      summarySpatialState: spatial,
      summaryGraspState: grasp,
      summaryXiezhiState: text("xiezhiRuntimeStatus", "WAITING"),
      summaryMujocoState: mujoco,
    };
    Object.entries(values).forEach(([id, value]) => {
      const node = byId(id);
      if (node) node.textContent = value;
    });

    const grounded = target !== "等待定位 WAITING" && target !== "—";
    document.querySelector('[data-summary-step="grounding"]')?.classList.toggle("is-active", grounded);
    document.querySelector('[data-summary-step="mask"]')?.classList.toggle("is-active", values.summaryMaskState === "READY");
    if (grounded && target !== lastGroundingMessage) {
      addMessage("assistant", "云冈娘", `我找到目标：${target}。FastSAM 正在使用锁定区域继续工作。`);
      lastGroundingMessage = target;
    }
  }

  syncTabs();
  updateSummary();
  window.setInterval(() => {
    syncTabs();
    updateSummary();
  }, 650);
})();
