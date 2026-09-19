// NARMA's approved N cut. Decoration never delays content or calls the server.
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
const running = new Map();
const pendingStates = new Set(['uploading', 'queued', 'processing']);

function visible(target) {
  return target?.isConnected && !target.closest('[hidden]') &&
    document.visibilityState !== 'hidden' && target.getClientRects().length > 0;
}

function run(target, className, duration, dispose = () => {}) {
  if (!visible(target) || reducedMotion.matches || running.has(target)) return false;
  const finish = () => {
    clearTimeout(timer);
    target.removeEventListener('animationend', ended);
    target.classList.remove(className);
    target.style.removeProperty('--narma-cut-duration');
    running.delete(target);
    dispose();
  };
  const ended = event => {
    if (['narma-cut-line', 'narma-episode-cut'].includes(event.animationName)) finish();
  };
  const timer = setTimeout(finish, duration + 150);
  running.set(target, finish);
  target.style.setProperty('--narma-cut-duration', `${duration}ms`);
  target.addEventListener('animationend', ended);
  target.classList.add(className);
  return true;
}

export function paintNarmaMark(target) {
  if (!target || target.classList.contains('narma-mark')) return;
  target.classList.add('narma-mark');
  target.setAttribute('aria-hidden', 'true');
  target.replaceChildren();
  for (const part of ['upper', 'lower', 'line']) {
    const span = document.createElement('span');
    span.className = `narma-cut-${part}`;
    if (part !== 'line') span.textContent = 'N';
    target.append(span);
  }
}

export function playNarmaCut(target, duration = 800) {
  paintNarmaMark(target);
  return run(target, 'narma-cut-playing', duration);
}

// One non-blocking, 4.9-second introduction per visible mount. The SVG has a
// stable NV fallback; motion never hides controls or waits for network/font loads.
let signatureId = 0;
export function mountNarmaSignature(host, { compact = false } = {}) {
  if (!host || host.dataset.signatureMounted) return;
  host.dataset.signatureMounted = 'true';
  host.classList.add('narma-signature');
  if (compact) host.classList.add('narma-signature-compact');
  const id = `narma-signature-${++signatureId}`;
  // A two-unit clip overlap avoids an antialias seam before the intended cut.
  const letters = `<g class="signature-letter-n"><text>N</text></g><g class="signature-letter-v"><text>V</text></g><g class="signature-rest"><text x="155" y="148">ARMA</text><text x="155" y="248">ISION</text></g>`;
  host.innerHTML = `<div class="signature-stage" role="img" aria-label="Narma Vision — твоя игра, твои решения">
    <span class="signature-index" aria-hidden="true">NV / VISION IN MOTION</span>
    <svg class="signature-art" viewBox="0 0 560 340" fill="none" aria-hidden="true" focusable="false">
      <defs>
        <clipPath id="${id}-upper"><path d="M0 0H560V112L0 286Z"/></clipPath>
        <clipPath id="${id}-lower"><path d="M0 284L560 110V340H0Z"/></clipPath>
      </defs>
      <g clip-path="url(#${id}-upper)"><g class="signature-half signature-half-upper">${letters}</g></g>
      <g clip-path="url(#${id}-lower)"><g class="signature-half signature-half-lower">${letters}</g></g>
      <path class="signature-drop" d="M64 28V94"/>
      <path class="signature-slash" d="M133 244L427 152" pathLength="1"/>
    </svg>
    <span class="signature-name" aria-hidden="true">NARMA VISION</span>
    <span class="signature-axis" aria-hidden="true">ТВОЯ ИГРА. ТВОИ РЕШЕНИЯ.</span>
  </div>`;
  let introducedHere = false;
  let inView = false;
  const introduce = () => {
    if (introducedHere || !inView || !visible(host)) return;
    introducedHere = true;
    observer.disconnect();
    document.removeEventListener('visibilitychange', introduce);
    if (!reducedMotion.matches) run(host, 'signature-playing', 4900);
  };
  const observer = new IntersectionObserver(entries => {
    inView = entries.some(entry => entry.isIntersecting && entry.intersectionRatio >= .25);
    introduce();
  }, { threshold: .25 });
  document.addEventListener('visibilitychange', introduce);
  observer.observe(host);
}

// Progressive enhancement: content is visible even without animation support.
// Observe only editorial blocks, never live messages, form errors or polling rows.
const revealTargets = [
  '.human-card > h2', '.human-intro > p', '.human-person', '.human-focus > h3',
  '.page-heading', '.practice-feature > .eyebrow', '.practice-feature > h1',
  '.practice-feature > p', '.practice-feature > .button-row', '.practice-feature > .feature-note',
  '.vision-path > a', '.section-heading', '.home-news', '.personal-promo',
  '.workspace-intro > div:first-child', '.card-heading', '.coach-overview',
  '.coach-section > h2', '.coach-summary', '.program-focus > h2', '.program-action',
  '.lesson-stage-intro', '.lesson-card > h3', '.lesson-question', '.lesson-copy',
  '.profile-wizard h2', '.profile-question legend', '.profile-scenario',
  '.profile-guidance > h3', '.profile-guidance > p', '.report-section > h3',
  '.next-game-section > .eyebrow', '.profile-summary > h2'
].join(',');
const revealed = new WeakSet();
const observed = new Set();
const interfaceAnimations = new Set();
function animateInterface(target, frames, options) {
  if (reducedMotion.matches || !visible(target) || !target.animate) return;
  const animation = target.animate(frames, options);
  interfaceAnimations.add(animation);
  const release = () => interfaceAnimations.delete(animation);
  animation.finished.then(release, release);
  return animation;
}
const revealObserver = new IntersectionObserver(entries => {
  let order = 0;
  for (const entry of entries) {
    if (!entry.isIntersecting || !visible(entry.target)) continue;
    revealObserver.unobserve(entry.target);
    observed.delete(entry.target);
    revealed.add(entry.target);
    // Text reveals by a moving edge at full contrast. Controls keep stable hit boxes.
    const interactive = entry.target.matches('a') || entry.target.querySelector('button,a,input,select');
    const frames = interactive ? [
      { boxShadow: '0 0 0 2px rgba(255,76,0,.32)' }, { boxShadow: '0 0 0 8px rgba(255,76,0,0)' }
    ] : [
      { clipPath: 'inset(0 0 80% 0)', transform: 'translateY(22px)' },
      { clipPath: 'inset(0 0 0% 0)', transform: 'translateY(0)' }
    ];
    animateInterface(entry.target, frames, { duration: 1050, delay: Math.min(order++, 4) * 95,
      easing: 'cubic-bezier(.22,1,.36,1)', fill: 'backwards' });
  }
}, { threshold: .08 });
let scanFrame = 0;
function scanMotion() {
  scanFrame = 0;
  for (const target of observed) {
    if (!target.isConnected) { revealObserver.unobserve(target); observed.delete(target); }
  }
  for (const target of document.querySelectorAll(revealTargets)) {
    if (revealed.has(target) || observed.has(target) || target.closest('[role=status], [role=alert], [role=log], .chat-message')) continue;
    observed.add(target);
    revealObserver.observe(target);
  }
}
new MutationObserver(() => {
  if (!scanFrame) scanFrame = requestAnimationFrame(scanMotion);
}).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['hidden'] });
scanMotion();

// Delegated activation also covers controls rendered after login / API updates.
// No preventDefault or delayed navigation; one activation still means one action.
const pressable = 'button, a.button, .account-link, .workspace-shortcuts a, .main-nav a, .vision-path > a, .profile-choice, summary';
const pressed = new WeakMap();
function pressFeedback(event) {
  if (event.type === 'pointerdown' && (event.button !== 0 || event.isPrimary === false)) return;
  if (event.type === 'keydown' && (!['Enter', ' '].includes(event.key) || event.repeat)) return;
  const target = event.target.closest?.(pressable);
  if (!target || target.matches(':disabled,[aria-disabled="true"]') || target.closest('[inert]')) return;
  pressed.get(target)?.cancel();
  const animation = animateInterface(target, [
    { transform: 'scale(1)', boxShadow: '0 0 0 0 rgba(255,76,0,.5)' },
    { transform: 'scale(.955)', boxShadow: '0 0 0 3px rgba(255,76,0,.35)', offset: .12 },
    { transform: 'scale(1)', boxShadow: '0 0 0 9px rgba(255,76,0,0)' }
  ], { duration: 480, easing: 'cubic-bezier(.22,1,.36,1)' });
  if (animation) pressed.set(target, animation);
}
document.addEventListener('pointerdown', pressFeedback, { passive: true });
document.addEventListener('keydown', pressFeedback);

export function playEpisodeCut(target) {
  if (!visible(target) || reducedMotion.matches || running.has(target)) return false;
  const line = document.createElement('span');
  line.className = 'narma-episode-line';
  line.setAttribute('aria-hidden', 'true');
  target.classList.add('narma-episode-target');
  target.append(line);
  return run(target, 'narma-episode-playing', 360, () => line.remove());
}

export function createCompletionMotion() {
  const states = new Map();
  return {
    reset() { states.clear(); },
    observe(job, target, ready) {
      const previous = states.get(job.id);
      states.set(job.id, job.state);
      if (states.size > 100) states.delete(states.keys().next().value);
      // Loading a saved report, polling it, or changing its display is not a
      // new analysis. Only an observed pending -> ready transition can play.
      if (ready && job.state === 'ready' && pendingStates.has(previous)) return playNarmaCut(target, 560);
      return false;
    }
  };
}

function stopMotion() {
  for (const animation of [...interfaceAnimations]) animation.cancel();
  for (const finish of [...running.values()]) finish();
}
reducedMotion.addEventListener('change', () => { if (reducedMotion.matches) stopMotion(); });
document.addEventListener('visibilitychange', () => { if (document.hidden) stopMotion(); });
window.addEventListener('pagehide', stopMotion);

for (const mark of document.querySelectorAll('.brand-symbol, .brand-mark, [data-narma-mark]')) paintNarmaMark(mark);
const brand = document.querySelector('.brand .narma-mark');
let introduced = false;
try { introduced = sessionStorage.getItem('narma.n-cut.introduced') === '1'; } catch { /* Static mark still works. */ }
if (!introduced && location.pathname !== '/' && playNarmaCut(brand)) {
  try { sessionStorage.setItem('narma.n-cut.introduced', '1'); } catch { /* Storage is optional. */ }
}
