(() => {
  "use strict";

  const title = document.querySelector("#xiezhiPreviewTitle");
  const copy = document.querySelector("#xiezhiPreviewCopy");
  const notice = document.querySelector("#notice");
  const actions = [...document.querySelectorAll("[data-xiezhi-action]")];
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
})();
