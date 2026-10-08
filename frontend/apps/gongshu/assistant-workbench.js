(() => {
  const byId = (id) => document.getElementById(id);
  const tabs = [...document.querySelectorAll("[data-workspace-tab]")];
  const messages = byId("assistantMessages");
  const input = byId("vlmInstruction");
  const groundButton = byId("vlmGroundButton");
  const diagnostics = byId("xiezhiLab");
  const diagnosticsToggle = byId("expertDiagnosticsToggle");
  let advisorMode = window.GongshuAdvisorMode?.isAdvisorMode() || false;
  let lastGroundingMessage = "";
  let chatStreamId = "";
  let lastChatSequence = 0;
  const renderedFeedbackEvents = new Set();

  function assistantName() {
    return advisorMode ? "Gongshu Assistant" : "云冈娘";
  }

  function formalizeAssistantCopy(text) {
    return String(text)
      .replace("收到，我正在让本地视觉模型定位目标。", "已收到指令，正在请求视觉 grounding。")
      .replace("我找到目标：", "目标已定位：")
      .replace("左侧目标已确认。", "Target selection confirmed: left.")
      .replace("右侧目标已确认。", "Target selection confirmed: right.");
  }

  function applyAdvisorCopy() {
    const formal = advisorMode;
    const copy = {
      assistantIdentityEyebrow: formal ? "GONGSHU ASSISTANT MODE" : "GONGSHU INTERNAL MODE",
      assistantDisplayName: formal ? "Gongshu Assistant" : "云冈娘",
      assistantDisplayEnglish: formal ? "Gongshu Assistant" : "Yungang-chan",
      assistantIdentitySubtitle: formal ? "Formal Interactive Control" : "Gongshu Interactive Assistant",
      assistantReadyAuthor: formal ? "GONGSHU ASSISTANT · READY" : "云冈娘 · READY",
      assistantReadyCopy: formal
        ? "自然语言控制已就绪。请输入目标指令，交由 Gongshu 视觉工作区处理。"
        : "你好，我是云冈娘。告诉我想抓哪个目标，我会把你的话交给公输视觉工作区。",
      assistantSystemCopy: formal
        ? "Gongshu Assistant 负责交互；Xiezhi Decision 负责后台决策。"
        : "我负责陪你交互；獬豸负责后台决策解释。",
      assistantSystemAuthor: formal ? "XIEZHI DECISION" : "WORKSPACE",
      assistantCommandTitle: formal ? "自然语言指令" : "告诉我怎么做",
      assistantRoleNoteLabel: formal ? "导师模式 · 正式工作台" : "内部模式 · 日常工作台",
      assistantRoleNoteCopy: formal ? "Gongshu Assistant / Xiezhi Decision" : "温和交互，明确行动。",
    };
    Object.entries(copy).forEach(([id, value]) => {
      const node = byId(id);
      if (node) node.textContent = value;
    });
    document.querySelectorAll('[data-assistant-message="true"]').forEach((message) => {
      const author = message.querySelector(".message-author");
      const copyNode = message.querySelector("p");
      if (author) author.textContent = assistantName();
      if (copyNode) copyNode.textContent = formal
        ? message.dataset.formalCopy || formalizeAssistantCopy(message.dataset.petCopy || copyNode.textContent)
        : message.dataset.petCopy || copyNode.textContent;
    });
    document.querySelectorAll(".assistant-message.is-grasp-feedback").forEach((message) => {
      const author = message.querySelector(".message-author");
      if (!author) return;
      author.textContent = message.dataset.messageType === "system_error"
        ? "SYSTEM FEEDBACK · EXECUTION STATUS"
        : formal ? "Gongshu Assistant · EXECUTION FEEDBACK" : "云冈娘 · 抓取反馈";
    });
  }

  function addMessage(kind, author, text) {
    if (!messages || !text) return;
    const message = document.createElement("article");
    message.className = `assistant-message is-${kind}`;
    if (kind === "assistant") {
      message.dataset.assistantMessage = "true";
      message.dataset.petCopy = text;
      message.dataset.formalCopy = formalizeAssistantCopy(text);
    }
    const label = document.createElement("span");
    label.className = "message-author";
    label.textContent = author;
    const copy = document.createElement("p");
    copy.textContent = text;
    message.append(label, copy);
    messages.append(message);
    messages.scrollTop = messages.scrollHeight;
  }

  function appendFeedbackLine(parent, label, value) {
    const row = document.createElement("div");
    const key = document.createElement("dt");
    key.textContent = label;
    const copy = document.createElement("dd");
    copy.textContent = value || "—";
    row.append(key, copy);
    parent.append(row);
  }

  function addExecutionFeedback(event) {
    if (!messages || !event || !["grasp_feedback", "system_error"].includes(event.message_type)) return;
    const eventId = String(event.event_id || event.message_id || "").trim();
    const alreadyRendered = [...messages.querySelectorAll("[data-event-id]")]
      .some((node) => node.dataset.eventId === eventId);
    if (!eventId || renderedFeedbackEvents.has(eventId) || alreadyRendered) return;
    const metadata = event.metadata && typeof event.metadata === "object" ? event.metadata : {};
    const systemError = event.message_type === "system_error";
    window.dispatchEvent(new CustomEvent("gongshu:chat-event", { detail: event }));
    const message = document.createElement("article");
    message.className = `assistant-message is-grasp-feedback ${metadata.success ? "is-success" : "is-failure"}${systemError ? " is-system-error" : ""}`;
    message.dataset.messageType = event.message_type;
    message.dataset.eventId = eventId;
    const label = document.createElement("span");
    label.className = "message-author";
    label.textContent = systemError
      ? "系统反馈 · EXECUTION STATUS"
      : `${assistantName()} · 抓取反馈`;
    const title = document.createElement("strong");
    title.className = "feedback-title";
    title.textContent = systemError ? "系统未能完成本次抓取执行" : (metadata.success ? "抓取结果：成功" : "抓取结果：失败");
    const summary = document.createElement("p");
    summary.className = "feedback-summary";
    summary.textContent = metadata.summary || event.text || "抓取执行已结束。";
    message.append(label, title, summary);

    const details = document.createElement("dl");
    details.className = "feedback-details";
    appendFeedbackLine(details, "目标", metadata.target);
    if (metadata.candidate_id) appendFeedbackLine(details, "候选", metadata.candidate_id);
    appendFeedbackLine(details, "阶段", metadata.stage);
    if (metadata.failure_type) appendFeedbackLine(details, "失败类型", metadata.failure_type);
    appendFeedbackLine(details, "Attempt", metadata.attempt_id);
    message.append(details);

    const evidenceLines = metadata.failure_evidence?.human_evidence_lines;
    if (Array.isArray(evidenceLines) && evidenceLines.length) {
      const evidence = document.createElement("div");
      evidence.className = "feedback-evidence";
      const heading = document.createElement("span");
      heading.textContent = "执行证据";
      const list = document.createElement("ul");
      evidenceLines.forEach((line) => {
        const item = document.createElement("li");
        item.textContent = String(line);
        list.append(item);
      });
      evidence.append(heading, list);
      message.append(evidence);
    }

    const recommendation = document.createElement("div");
    recommendation.className = "feedback-recommendation";
    recommendation.textContent = `${systemError ? "处理建议" : "下一步建议"}：${metadata.recommended_action || "inspect_system_status_before_retry"}`;
    message.append(recommendation);
    messages.append(message);
    messages.scrollTop = messages.scrollHeight;
    renderedFeedbackEvents.add(eventId);
  }

  function addWorkflowUpdate(event) {
    if (!messages || !event || event.message_type !== "workflow_update") return;
    const eventId = String(event.event_id || event.message_id || "").trim();
    if (!eventId || renderedFeedbackEvents.has(eventId)) return;
    const metadata = event.metadata && typeof event.metadata === "object" ? event.metadata : {};
    const message = document.createElement("article");
    message.className = "assistant-message is-workflow-update";
    message.dataset.eventId = eventId;
    const label = document.createElement("span");
    label.className = "message-author";
    label.textContent = `${assistantName()} · 实验时间线`;
    const title = document.createElement("strong");
    title.className = "workflow-title";
    title.textContent = `${metadata.phase || "workflow"} · ${metadata.status || "updated"}`;
    const copy = document.createElement("p");
    copy.className = "workflow-summary";
    copy.textContent = event.text || "工作流状态已更新。";
    const detail = document.createElement("small");
    detail.className = "workflow-detail";
    const reason = metadata.reason || metadata.target_id || metadata.selected_candidate_id || metadata.state;
    detail.textContent = reason ? String(reason) : "真实后端阶段事件";
    message.append(label, title, copy, detail);
    messages.append(message);
    messages.scrollTop = messages.scrollHeight;
    renderedFeedbackEvents.add(eventId);
  }

  async function pollExecutionFeedback() {
    try {
      const response = await fetch(
        `/api/chat/events?after_sequence=${lastChatSequence}&t=${Date.now()}`,
        { cache: "no-store" },
      );
      if (!response.ok) return;
      const payload = await response.json();
      if (!Array.isArray(payload.events)) return;
      if (payload.stream_id && chatStreamId && payload.stream_id !== chatStreamId) {
        chatStreamId = payload.stream_id;
        lastChatSequence = 0;
        return;
      }
      chatStreamId = payload.stream_id || chatStreamId;
      if (payload.cursor_reset) lastChatSequence = 0;
      payload.events.forEach((event) => {
        if (event.message_type === "workflow_update") addWorkflowUpdate(event);
        else addExecutionFeedback(event);
        if (Number.isFinite(Number(event.sequence))) {
          lastChatSequence = Math.max(lastChatSequence, Number(event.sequence));
        }
      });
    } catch {
      // The server-side event stream and experiment record remain authoritative.
    }
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
        else addMessage("assistant", assistantName(), "当前还不能重新观察，请先连接视觉输入。");
        return;
      }
      if (command === "执行当前抓取") {
        addMessage("user", "你", command);
        const graspButton = byId("startGraspButton");
        if (graspButton && !graspButton.disabled) graspButton.click();
        else addMessage("assistant", assistantName(), "当前还没有可执行的抓取计划。");
        return;
      }
      if ((command === "抓左边那个" || command === "抓右边那个")
        && !advisorMode
        && groundButton?.disabled
        && window.GongshuYungangAssistant?.setMockTarget) {
        addMessage("user", "你", command);
        window.GongshuYungangAssistant.setMockTarget(command === "抓左边那个" ? "left" : "right");
        addMessage("assistant", assistantName(), command === "抓左边那个" ? "左侧目标已确认。" : "右侧目标已确认。");
        return;
      }
      if ((command === "抓左边那个" || command === "抓右边那个")
        && advisorMode
        && groundButton?.disabled) {
        addMessage("user", "你", command);
        addMessage("assistant", assistantName(), "视觉 grounding 尚未就绪，请先连接视觉输入。");
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
      if (command) addMessage("assistant", assistantName(), advisorMode
        ? "已收到指令，正在请求视觉 grounding。"
        : "收到，我正在让本地视觉模型定位目标。");
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
      addMessage("assistant", assistantName(), advisorMode
        ? `目标已定位：${target}。FastSAM 正在使用锁定区域继续工作。`
        : `我找到目标：${target}。FastSAM 正在使用锁定区域继续工作。`);
      lastGroundingMessage = target;
    }
  }

  window.addEventListener("gongshu:advisor-mode-change", (event) => {
    advisorMode = Boolean(event.detail?.advisorMode);
    applyAdvisorCopy();
  });
  applyAdvisorCopy();
  syncTabs();
  updateSummary();
  pollExecutionFeedback();
  window.setInterval(() => {
    syncTabs();
    updateSummary();
    pollExecutionFeedback();
  }, 650);
})();
