(() => {
  'use strict';

  const TOTAL_MS = 10000;
  const SCENE_MS = 2500;
  const READY_MS = 9400;
  const labels = [
    '01 · BRAND AWAKENING',
    '02 · VISION PERCEPTION',
    '03 · SPATIAL INTELLIGENCE',
    '04 · VISION LANGUAGE ACTION'
  ];

  const intro = document.getElementById('intro');
  const scenes = [...document.querySelectorAll('.scene')];
  const sceneLabel = document.getElementById('scene-label');
  const timecode = document.getElementById('timecode');
  const skipButton = document.getElementById('skip-intro');
  const replayButton = document.getElementById('replay-intro');
  const initializationHud = document.getElementById('system-initialization');
  const initializationMessage = document.getElementById('initialization-message');
  const initializationState = document.getElementById('initialization-state');
  const moduleRows = Object.fromEntries(
    [...document.querySelectorAll('.initialization-module')].map(row => [row.dataset.module, row])
  );
  let startTime = 0;
  let frameId = 0;
  let activeIndex = -1;
  let completionTimer = 0;
  let preparationToken = 0;
  let assetsHealthy = true;
  let lastInitializationPhase = '';

  function clamp(value, minimum = 0, maximum = 1) {
    return Math.min(maximum, Math.max(minimum, value));
  }

  function smoothstep(value) {
    const normalized = clamp(value);
    return normalized * normalized * (3 - 2 * normalized);
  }

  function interpolate(elapsed, start, end, from, to) {
    const progress = smoothstep((elapsed - start) / (end - start));
    return from + (to - from) * progress;
  }

  function setModuleProgress(name, value) {
    const row = moduleRows[name];
    if (!row) return;
    const progress = Math.round(clamp(value, 0, 100));
    row.classList.toggle('is-pending', progress === 0);
    row.classList.toggle('is-active', progress > 0 && progress < 100);
    row.classList.toggle('is-complete', progress === 100);
    row.querySelector('.module-track b').style.width = `${progress}%`;
    row.querySelector('.module-track').setAttribute('aria-valuenow', String(progress));
    row.querySelector('output').textContent = `${progress}%`;
  }

  function setInitializationPhase(phase, message, state) {
    if (phase === lastInitializationPhase) return;
    lastInitializationPhase = phase;
    initializationHud.dataset.state = phase;
    initializationMessage.textContent = message;
    initializationState.textContent = state;
  }

  function resetInitialization() {
    lastInitializationPhase = '';
    ['vision', 'spatial', 'language', 'action'].forEach(name => setModuleProgress(name, 0));
  }

  function updateInitialization(elapsed) {
    const vision = interpolate(elapsed, 0, 2000, 0, 100);
    const spatial = elapsed < 2500
      ? 0
      : elapsed < 5000
        ? interpolate(elapsed, 2500, 5000, 0, 60)
        : interpolate(elapsed, 5000, 7000, 60, 100);
    const language = elapsed < 5000
      ? 0
      : elapsed < 7500
        ? interpolate(elapsed, 5000, 7500, 0, 70)
        : interpolate(elapsed, 7500, 9200, 70, 100);
    const action = elapsed < 7500 ? 0 : interpolate(elapsed, 7500, READY_MS, 0, 100);

    setModuleProgress('vision', vision);
    setModuleProgress('spatial', spatial);
    setModuleProgress('language', language);
    setModuleProgress('action', action);

    if (elapsed >= READY_MS) {
      if (assetsHealthy) {
        setInitializationPhase('ready', 'All visual intelligence modules synchronized', 'SYSTEM READY');
      } else {
        setInitializationPhase('warning', 'Visual asset unavailable · continuing to Portal', 'ASSET WARNING');
      }
      return;
    }

    const sceneIndex = Math.min(3, Math.floor(elapsed / SCENE_MS));
    const messages = [
      'Initializing Jingwei Vision Core',
      'Synchronizing RGB-D perception pipeline',
      'Calibrating spatial intelligence',
      'Linking Vision · Language · Action'
    ];
    setInitializationPhase(`scene-${sceneIndex}`, messages[sceneIndex], 'BOOT SEQUENCE');
  }

  function resetSceneAnimations() {
    scenes.forEach(scene => {
      scene.querySelectorAll('img').forEach(image => {
        const freshImage = image.cloneNode(false);
        image.replaceWith(freshImage);
      });
    });
  }

  function setScene(index) {
    if (index === activeIndex || index < 0 || index >= scenes.length) return;
    scenes.forEach((scene, sceneIndex) => {
      const wasActive = scene.classList.contains('is-active');
      scene.classList.toggle('is-active', sceneIndex === index);
      scene.classList.toggle('is-leaving', wasActive && sceneIndex !== index);
      if (wasActive && sceneIndex !== index) {
        window.setTimeout(() => scene.classList.remove('is-leaving'), 300);
      }
    });
    activeIndex = index;
    intro.dataset.scene = String(index);
    sceneLabel.textContent = labels[index];
  }

  function formatTime(elapsed) {
    const safe = Math.max(0, Math.min(TOTAL_MS, Math.floor(elapsed)));
    const seconds = String(Math.floor(safe / 1000)).padStart(2, '0');
    const millis = String(safe % 1000).padStart(3, '0');
    return `00:${seconds}:${millis}`;
  }

  function tick(now) {
    const elapsed = now - startTime;
    const index = Math.min(3, Math.floor(elapsed / SCENE_MS));
    setScene(index);
    timecode.textContent = formatTime(elapsed);
    updateInitialization(elapsed);
    if (elapsed < TOTAL_MS) frameId = requestAnimationFrame(tick);
  }

  function complete() {
    if (intro.classList.contains('is-complete')) return;
    preparationToken += 1;
    cancelAnimationFrame(frameId);
    clearTimeout(completionTimer);
    timecode.textContent = formatTime(TOTAL_MS);
    updateInitialization(TOTAL_MS);
    intro.classList.remove('is-playing', 'is-preloading');
    intro.classList.add('is-complete');
    window.dispatchEvent(new CustomEvent('jingwei:intro-complete'));
    if (window.parent !== window) {
      window.parent.postMessage({ type: 'jingwei:intro-complete' }, '*');
    }
    const redirect = document.body.dataset.portalUrl;
    if (redirect) window.location.href = redirect;
  }

  function play() {
    cancelAnimationFrame(frameId);
    clearTimeout(completionTimer);
    activeIndex = -1;
    intro.classList.remove('is-complete', 'is-preloading', 'is-playing');
    intro.classList.toggle('has-asset-warning', !assetsHealthy);
    resetInitialization();
    resetSceneAnimations();
    void intro.offsetWidth;
    intro.classList.add('is-playing');
    setScene(0);
    startTime = performance.now();
    updateInitialization(0);
    frameId = requestAnimationFrame(tick);
    completionTimer = window.setTimeout(complete, TOTAL_MS);
  }

  function waitForImage(image) {
    if (image.complete) return Promise.resolve(image.naturalWidth > 0);
    return new Promise(resolve => {
      image.addEventListener('load', () => resolve(true), { once: true });
      image.addEventListener('error', () => resolve(false), { once: true });
    });
  }

  async function prepareAndPlay() {
    const token = ++preparationToken;
    intro.classList.add('is-preloading');
    resetInitialization();
    setInitializationPhase('preload', 'Preparing visual assets · 0/0', 'ASSET CHECK');

    const uniqueImages = [...new Map(
      [...document.images].map(image => [image.currentSrc || image.src, image])
    ).values()];
    let settled = 0;
    let failures = 0;
    initializationMessage.textContent = `Preparing visual assets · 0/${uniqueImages.length}`;

    await Promise.all(uniqueImages.map(async image => {
      const loaded = await waitForImage(image);
      settled += 1;
      if (!loaded) failures += 1;
      if (token === preparationToken) {
        initializationMessage.textContent = `Preparing visual assets · ${settled}/${uniqueImages.length}`;
      }
    }));

    if (token !== preparationToken) return;
    assetsHealthy = failures === 0;
    intro.classList.toggle('has-asset-warning', !assetsHealthy);
    intro.classList.remove('is-preloading');
    play();
  }

  skipButton.addEventListener('click', complete);
  replayButton.addEventListener('click', play);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') complete();
    if ((event.key === 'r' || event.key === 'R') && intro.classList.contains('is-complete')) play();
  });

  window.JingweiIntro = { play, complete, duration: TOTAL_MS };
  prepareAndPlay();
})();
