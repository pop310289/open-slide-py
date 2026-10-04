/* OpenSlide native player. No network requests, dynamic HTML, or dependencies. */
"use strict";

class OpenSlidePlayback {
  constructor(steps) {
    this.steps = steps.map(values => Array.from(new Set(values)).sort((a, b) => a - b));
    this.index = 0;
    this.revealed = 0;
    this.full = false;
  }
  get count() { return this.steps.length; }
  get stageCount() { return this.steps[this.index].length; }
  get canNext() { return (!this.full && this.revealed < this.stageCount) || this.index < this.count - 1; }
  get canPrevious() { return (!this.full && this.revealed > 0) || this.index > 0; }
  visible(step) { return this.full || this.steps[this.index].indexOf(step) < this.revealed; }
  go(index, complete = false) {
    this.index = Math.max(0, Math.min(this.count - 1, index));
    this.revealed = complete ? this.stageCount : 0;
  }
  next() {
    if (!this.full && this.revealed < this.stageCount) this.revealed += 1;
    else if (this.index < this.count - 1) this.go(this.index + 1);
  }
  previous() {
    if (!this.full && this.revealed > 0) this.revealed -= 1;
    else if (this.index > 0) this.go(this.index - 1, true);
  }
  setFull(value) { this.full = Boolean(value); }
  handleKey(event, modalOpen = false) {
    if (event.defaultPrevented || event.isComposing || event.altKey || event.ctrlKey || event.metaKey || modalOpen) return false;
    const target = event.target;
    const space = event.key === " " || event.key === "Spacebar";
    if (target && typeof target.closest === "function") {
      if (target.closest("input, textarea, select, [contenteditable], [role='textbox'], .os-notes")) return false;
      // A toolbar click leaves focus on its button. Presenter navigation must
      // keep working there, while Space remains the control's native action.
      if (space && target.closest("button, a, summary, [role='button'], [role='link']")) return false;
    }
    if (event.shiftKey && !space) return false;
    if (space) { if (event.shiftKey) this.previous(); else this.next(); }
    else if (event.key === "ArrowRight" || event.key === "PageDown") this.next();
    else if (event.key === "ArrowLeft" || event.key === "PageUp") this.previous();
    else if (event.key === "Home") this.go(0);
    else if (event.key === "End") this.go(this.count - 1, true);
    else return false;
    return true;
  }
}

(() => {
  if (typeof document === "undefined") return;
  const slides = Array.from(document.querySelectorAll("[data-os-slide]"));
  if (!slides.length) return;
  const byId = id => document.getElementById(id);
  const stepNodes = slides.map(slide => Array.from(slide.querySelectorAll("[data-os-step]")));
  const state = new OpenSlidePlayback(stepNodes.map(nodes => nodes.map(node => Number(node.dataset.osStep))));
  const body = document.body;
  const stage = byId("os-stage");
  const directory = byId("os-directory");
  const toolbox = byId("os-toolbox");
  const dialogs = [directory, toolbox];
  const cards = Array.from(directory.querySelectorAll("[data-os-go]"));
  let showNotes = false;
  let lastIndex = -1;
  let timerStarted = null;
  let timerElapsed = 0;
  let gesture = null;
  let thumbnailsReady = false;

  function readHash() {
    const match = /^#slide-([1-9]\d*)$/.exec(location.hash);
    if (!match) return null;
    const index = Number(match[1]) - 1;
    return Number.isSafeInteger(index) && index < state.count ? index : null;
  }

  function timerText(milliseconds) {
    const seconds = Math.max(0, Math.floor(milliseconds / 1000));
    const minutes = Math.floor(seconds / 60);
    return String(minutes).padStart(2, "0") + ":" + String(seconds % 60).padStart(2, "0");
  }

  function updateTimer() {
    const elapsed = timerElapsed + (timerStarted === null ? 0 : performance.now() - timerStarted);
    byId("os-timer").textContent = timerText(elapsed);
    byId("os-timer-toggle").textContent = timerStarted === null ? "開始計時" : "暫停計時";
    byId("os-timer-toggle").setAttribute("aria-pressed", String(timerStarted !== null));
  }

  function closeDialog(dialog) { if (dialog.open) dialog.close(); }
  function refresh(updateHash = true) {
    slides.forEach((slide, index) => {
      const active = index === state.index;
      slide.hidden = !active;
      if (active && lastIndex !== index) {
        slide.classList.remove("os-enter");
        // Reading layout restarts the optional authored fade on a later visit.
        void slide.offsetWidth;
        slide.classList.add("os-enter");
      }
      if (active) stepNodes[index].forEach(node => {
        const hidden = !state.visible(Number(node.dataset.osStep));
        node.classList.toggle("os-step-hidden", hidden);
        node.setAttribute("aria-hidden", String(hidden));
        node.querySelectorAll("a").forEach(link => {
          if (hidden) link.setAttribute("tabindex", "-1");
          else link.removeAttribute("tabindex");
        });
      });
      slide.querySelector("[data-os-notes]").open = showNotes && active;
      cards[index].setAttribute("aria-current", active ? "page" : "false");
    });
    lastIndex = state.index;
    byId("os-page").textContent = (state.index + 1) + " / " + state.count;
    byId("os-progress").value = state.index + 1;
    byId("os-prev").disabled = !state.canPrevious;
    byId("os-next").disabled = !state.canNext;
    byId("os-step-status").textContent = state.full ? "完整顯示" : state.stageCount ? "逐步 " + state.revealed + " / " + state.stageCount : "本頁完整顯示";
    body.classList.toggle("os-show-notes", showNotes);
    byId("os-notes-toggle").setAttribute("aria-pressed", String(showNotes));
    byId("os-full-toggle").setAttribute("aria-pressed", String(state.full));
    if (updateHash) {
      const hash = "#slide-" + (state.index + 1);
      if (location.hash !== hash) {
        // file:// browsers may restrict history; hash navigation remains usable.
        try { history.replaceState(null, "", hash); }
        catch (_) { location.hash = hash; }
      }
    }
  }

  function navigate(direction) {
    if (direction > 0) state.next(); else state.previous();
    refresh();
  }

  function buildThumbnails() {
    if (thumbnailsReady) return;
    slides.forEach((slide, index) => {
      const clone = slide.querySelector("svg").cloneNode(true);
      const ids = new Map();
      clone.querySelectorAll("[id]").forEach(node => {
        const previous = node.id;
        const next = "os-thumb-" + index + "-" + previous;
        ids.set(previous, next);
        node.id = next;
      });
      [clone, ...clone.querySelectorAll("*")].forEach(node => {
        node.classList.remove("os-step-hidden");
        node.removeAttribute("aria-hidden");
        node.removeAttribute("data-os-step");
        if (node.hasAttribute("aria-labelledby")) {
          node.setAttribute("aria-labelledby", node.getAttribute("aria-labelledby").split(/\s+/).map(id => ids.get(id) || id).join(" "));
        }
        if (node.hasAttribute("clip-path")) {
          node.setAttribute("clip-path", node.getAttribute("clip-path").replace(/url\(#([^)]*)\)/g, (whole, id) => "url(#" + (ids.get(id) || id) + ")"));
        }
        if (node.tagName.toLowerCase() === "a") {
          // A preview sits inside a card link and must not contain nested links.
          const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
          while (node.firstChild) group.appendChild(node.firstChild);
          node.replaceWith(group);
        }
      });
      clone.setAttribute("aria-hidden", "true");
      clone.removeAttribute("role");
      cards[index].querySelector(".os-preview").appendChild(clone);
    });
    thumbnailsReady = true;
  }

  byId("os-prev").addEventListener("click", () => navigate(-1));
  byId("os-next").addEventListener("click", () => navigate(1));
  byId("os-catalog").addEventListener("click", () => { buildThumbnails(); directory.showModal(); });
  byId("os-tools").addEventListener("click", () => toolbox.showModal());
  document.querySelectorAll("[data-os-close]").forEach(button => button.addEventListener("click", () => closeDialog(button.closest("dialog"))));
  document.addEventListener("click", event => {
    const link = event.target.closest("a[href^='#slide-']");
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const match = /^#slide-([1-9]\d*)$/.exec(link.getAttribute("href"));
    const index = match ? Number(match[1]) - 1 : -1;
    if (index < 0 || index >= state.count) return;
    event.preventDefault();
    state.go(index);
    dialogs.forEach(closeDialog);
    refresh();
    stage.focus({preventScroll: true});
  });
  byId("os-notes-toggle").addEventListener("click", () => { showNotes = !showNotes; refresh(); closeDialog(toolbox); });
  byId("os-full-toggle").addEventListener("click", () => { state.setFull(!state.full); refresh(); closeDialog(toolbox); });
  byId("os-timer-toggle").addEventListener("click", () => {
    if (timerStarted === null) timerStarted = performance.now();
    else { timerElapsed += performance.now() - timerStarted; timerStarted = null; }
    updateTimer();
  });
  byId("os-timer-reset").addEventListener("click", () => { timerElapsed = 0; if (timerStarted !== null) timerStarted = performance.now(); updateTimer(); });
  byId("os-fullscreen").addEventListener("click", async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
      byId("os-message").textContent = "";
      closeDialog(toolbox);
    } catch (_) { byId("os-message").textContent = "目前瀏覽器無法啟用全螢幕；仍可使用完整播放功能。"; }
  });
  document.addEventListener("fullscreenchange", () => {
    const active = Boolean(document.fullscreenElement);
    byId("os-fullscreen").textContent = active ? "結束全螢幕" : "全螢幕";
    byId("os-fullscreen").setAttribute("aria-pressed", String(active));
  });
  document.addEventListener("keydown", event => {
    if (state.handleKey(event, dialogs.some(dialog => dialog.open))) {
      refresh();
      event.preventDefault();
    }
  });
  stage.addEventListener("touchstart", event => {
    if (event.touches.length !== 1 || event.target.closest("a, button, .os-notes")) { gesture = null; return; }
    const point = event.touches[0];
    gesture = {x: point.clientX, y: point.clientY, time: performance.now()};
  }, {passive: true});
  stage.addEventListener("touchmove", event => { if (event.touches.length !== 1) gesture = null; }, {passive: true});
  stage.addEventListener("touchcancel", () => { gesture = null; }, {passive: true});
  stage.addEventListener("touchend", event => {
    if (!gesture || event.touches.length || !event.changedTouches.length) return;
    const point = event.changedTouches[0];
    const dx = point.clientX - gesture.x;
    const dy = point.clientY - gesture.y;
    if (performance.now() - gesture.time < 1000 && Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.6) navigate(dx < 0 ? 1 : -1);
    gesture = null;
  }, {passive: true});
  window.addEventListener("hashchange", () => {
    const index = readHash();
    if (index !== null && index !== state.index) { state.go(index); refresh(false); }
  });

  const initialIndex = readHash();
  if (initialIndex !== null) state.go(initialIndex);
  // Enhance only after all setup succeeds. Without scripts, the document and
  // every reveal group retain their normal full-content reading/print layout.
  body.classList.add("os-enhanced");
  document.querySelectorAll("[data-os-controls]").forEach(node => { node.hidden = false; });
  updateTimer();
  refresh();
  window.setInterval(updateTimer, 500);
})();
