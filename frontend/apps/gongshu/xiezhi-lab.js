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

  async function refreshRuntimeStatus() {
    if (!runtimeStatus || !connectionStatus || !runtimeContext || !latestEvent) return;
    try {
      const response = await fetch("/api/xiezhi/status", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const state = await response.json();
      runtimeStatus.textContent = String(state.status || "unknown").toUpperCase();
      connectionStatus.textContent = state.connected ? "CONNECTED" : "OFFLINE";
      const context = state.context || {};
      runtimeContext.textContent = context.simulation
        ? `Gongshu ${eventLabel(context.simulation)}`
        : "Gongshu";
      latestEvent.textContent = eventLabel(state.last_event);
    } catch (_error) {
      runtimeStatus.textContent = "UNAVAILABLE";
      connectionStatus.textContent = "OFFLINE";
    }
  }

  refreshRuntimeStatus();
  window.setInterval(refreshRuntimeStatus, 1000);
})();
