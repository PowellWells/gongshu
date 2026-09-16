(() => {
  "use strict";

  const title = document.querySelector("#xiezhiPreviewTitle");
  const copy = document.querySelector("#xiezhiPreviewCopy");
  const notice = document.querySelector("#notice");
  const actions = [...document.querySelectorAll("[data-xiezhi-action]")];
  const runtimeStatus = document.querySelector("#xiezhiRuntimeStatus");
  const connectionStatus = document.querySelector("#xiezhiConnectionStatus");
  const runtimeContext = document.querySelector("#xiezhiRuntimeContext");
  const latestEvent = document.querySelector("#xiezhiLatestEvent");
  let noticeTimer = 0;

  if (!title || !copy || !notice || !actions.length) return;

  function showPlaceholderNotice(action) {
    window.clearTimeout(noticeTimer);
    notice.textContent = `${action} 已在 Gongshu 内启用；当前等待观测与实验上下文。`;
    notice.className = "workspace-notice is-success";
    notice.hidden = false;
    noticeTimer = window.setTimeout(() => { notice.hidden = true; }, 3600);
  }

  actions.forEach((button) => {
    button.addEventListener("click", () => {
      actions.forEach((item) => item.classList.remove("is-selected"));
      button.classList.add("is-selected");
      title.textContent = button.dataset.preview;
      copy.textContent = button.dataset.copy;
      showPlaceholderNotice(button.dataset.xiezhiAction);
    });
  });

  function eventLabel(value) {
    if (!value) return "NONE";
    return String(value).split("_").map((part) => (
      part.charAt(0).toUpperCase() + part.slice(1)
    )).join(" ");
  }

  function renderRuntimeState(state) {
    if (!runtimeStatus || !connectionStatus || !runtimeContext || !latestEvent) return;
    runtimeStatus.textContent = String(state.status || "unknown").toUpperCase();
    const active = state.active_provider === "xiezhi" ? "Xiezhi" : "Gongshu";
    connectionStatus.textContent = `${active} · ${state.algorithm || "UNKNOWN"}`;
    runtimeContext.textContent = state.decision_available ? "AVAILABLE" : "NOT AVAILABLE";
    const decision = state.last_decision;
    latestEvent.textContent = decision
      ? `${eventLabel(decision.selected_action)} · ${decision.selected_candidate_id || decision.reason}`
      : "NONE";
  }

  async function refreshRuntimeStatus() {
    if (!runtimeStatus || !connectionStatus || !runtimeContext || !latestEvent) return;
    try {
      const response = await fetch("/api/intelligence/state", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      renderRuntimeState(await response.json());
    } catch (_error) {
      runtimeStatus.textContent = "UNAVAILABLE";
      connectionStatus.textContent = "OFFLINE";
    }
  }

  window.addEventListener("gongshu:intelligence-state", (event) => {
    if (event.detail) renderRuntimeState(event.detail);
  });
  refreshRuntimeStatus();
  window.setInterval(refreshRuntimeStatus, 1000);
})();
