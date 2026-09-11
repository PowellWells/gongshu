(() => {
  "use strict";

  const motionToggle = document.querySelector("#motionToggle");
  const statusDialog = document.querySelector("#statusDialog");
  const momentRuntimeRow = document.querySelector("#momentRuntimeRow");
  const footerStatus = document.querySelector("#footerStatus");
  const footerStatusCopy = footerStatus.querySelector("small");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const introOverlay = document.querySelector("#introOverlay");
  const introFrame = document.querySelector("#introFrame");
  const portalRegions = [...document.querySelectorAll(".portal-header, .vision-home, .portal-footer")];
  let introFallbackTimer = 0;
  let introRemovalTimer = 0;
  let introDismissed = false;

  function setPortalInteractive(enabled) {
    portalRegions.forEach((region) => {
      region.inert = !enabled;
      if (enabled) {
        region.removeAttribute("aria-hidden");
      } else {
        region.setAttribute("aria-hidden", "true");
      }
    });
  }

  function removeIntroOverlay() {
    if (!introOverlay?.isConnected) return;
    introOverlay.remove();
  }

  function dismissIntro() {
    if (!introOverlay || introDismissed) return;
    introDismissed = true;
    window.clearTimeout(introFallbackTimer);
    window.removeEventListener("message", handleIntroMessage);
    document.body.classList.remove("intro-active");
    setPortalInteractive(true);
    introOverlay.classList.add("is-exiting");
    introOverlay.addEventListener("transitionend", removeIntroOverlay, { once: true });
    introRemovalTimer = window.setTimeout(removeIntroOverlay, 700);
  }

  function handleIntroMessage(event) {
    if (!introFrame || event.source !== introFrame.contentWindow) return;
    const messageType = typeof event.data === "string" ? event.data : event.data?.type;
    if (messageType !== "jingwei:intro-complete") return;
    dismissIntro();
  }

  function initializeIntroOverlay() {
    if (!introOverlay || !introFrame) {
      document.body.classList.remove("intro-active");
      setPortalInteractive(true);
      return;
    }
    window.clearTimeout(introRemovalTimer);
    setPortalInteractive(false);
    window.addEventListener("message", handleIntroMessage);
    introFallbackTimer = window.setTimeout(dismissIntro, 11200);
  }

  function readMotionPreference() {
    try {
      const stored = window.localStorage.getItem("xuanshu-portal-motion") || window.localStorage.getItem("jingwei-portal-motion");
      if (stored !== null) return stored === "enabled";
    } catch {
      // A blocked localStorage should not prevent direct-file use.
    }
    return !reduceMotion.matches;
  }

  function applyMotion(enabled) {
    document.documentElement.classList.toggle("motion-enabled", enabled);
    document.documentElement.classList.toggle("reduce-motion", !enabled);
    motionToggle.checked = enabled;
    try {
      window.localStorage.setItem("xuanshu-portal-motion", enabled ? "enabled" : "disabled");
    } catch {
      // Motion preference remains active for the current page session.
    }
  }

  function openDialog(dialog) {
    if (!dialog) return;
    if (typeof dialog.showModal === "function") {
      dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }
  }

  function closeDialog(dialog) {
    if (!dialog) return;
    if (typeof dialog.close === "function") {
      dialog.close();
    } else {
      dialog.removeAttribute("open");
    }
  }

  function setMomentStatus(online) {
    momentRuntimeRow.classList.toggle("is-ready", online);
    momentRuntimeRow.classList.toggle("is-offline", !online);
    momentRuntimeRow.querySelector("small").textContent = online ? "Moment · Jingwei Nano 已连接" : "Moment 本地模型未连接";
    momentRuntimeRow.querySelector("b").textContent = online ? "ONLINE" : "OFFLINE";
    footerStatusCopy.textContent = online ? "经纬已连接 · 公输等待运行数据" : "部分运行源尚未连接";
  }

  async function checkMomentRuntime() {
    if (window.location.protocol === "file:") {
      setMomentStatus(false);
      return;
    }
    try {
      const response = await fetch("./api/health", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      setMomentStatus(payload?.status === "ok");
    } catch {
      setMomentStatus(false);
    }
  }

  document.querySelectorAll("[data-open-dialog]").forEach((button) => {
    button.addEventListener("click", () => openDialog(document.querySelector(`#${button.dataset.openDialog}`)));
  });
  document.querySelectorAll("[data-close-dialog]").forEach((button) => {
    button.addEventListener("click", () => closeDialog(button.closest("dialog")));
  });
  document.querySelectorAll("dialog").forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) closeDialog(dialog);
    });
  });

  document.querySelector("#statusButton").addEventListener("click", () => openDialog(statusDialog));
  footerStatus.addEventListener("click", () => openDialog(statusDialog));
  motionToggle.addEventListener("change", () => applyMotion(motionToggle.checked));

  initializeIntroOverlay();
  applyMotion(readMotionPreference());
  checkMomentRuntime();
})();
