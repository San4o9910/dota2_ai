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
    if (['narma-cut-line', 'narma-signature-cut', 'narma-episode-cut'].includes(event.animationName)) finish();
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

// A visible, replayable introduction. The old 40px header accent alone was
// easily missed. No requests, account state, blocking overlay or endless loop.
export function mountNarmaSignature(host, { compact = false } = {}) {
  if (!host || host.dataset.signatureMounted) return;
  host.dataset.signatureMounted = 'true';
  host.classList.add('narma-signature');
  if (compact) host.classList.add('narma-signature-compact');
  host.innerHTML = `<button type="button" class="signature-replay" aria-label="Повторить фирменную анимацию NARMA"><span class="signature-stage" aria-hidden="true"><span class="signature-index">NV / 01</span><span class="signature-mark"></span><span class="signature-wordmark">NARMA<span>VISION</span></span><span class="signature-axis">ТВОЯ ИГРА. ТВОИ РЕШЕНИЯ.</span></span><span class="signature-caption"><span class="signature-replay-icon" aria-hidden="true">↻</span><span data-signature-label>Повторить анимацию</span></span></button><p class="signature-motion-note" hidden>Движение отключено в настройках устройства.</p>`;
  const mark = host.querySelector('.signature-mark');
  const button = host.querySelector('button');
  const label = host.querySelector('[data-signature-label]');
  const note = host.querySelector('.signature-motion-note');
  paintNarmaMark(mark);
  const syncPreference = () => {
    button.disabled = reducedMotion.matches;
    label.textContent = reducedMotion.matches ? 'Фирменный знак NARMA' : 'Повторить анимацию';
    note.hidden = !reducedMotion.matches;
  };
  syncPreference();
  reducedMotion.addEventListener('change', syncPreference);
  button.addEventListener('click', () => playNarmaCut(mark, 1100));
  let introducedHere = false;
  let inView = false;
  const introduce = () => {
    if (introducedHere || !inView || !visible(mark) || reducedMotion.matches) return;
    let seen = false;
    try { seen = sessionStorage.getItem('narma.n-cut.featured.v1') === '1'; } catch { /* Optional storage. */ }
    if (seen) { introducedHere = true; return; }
    if (playNarmaCut(mark, 1100)) {
      introducedHere = true;
      try { sessionStorage.setItem('narma.n-cut.featured.v1', '1'); } catch { /* At most once for this mount. */ }
    }
  };
  // Hidden workspaces and offscreen mobile scenes must not consume the intro.
  const observer = new IntersectionObserver(entries => {
    inView = entries.some(entry => entry.isIntersecting && entry.intersectionRatio >= .6);
    if (inView) {
      requestAnimationFrame(() => requestAnimationFrame(introduce));
    }
  }, { threshold: .6 });
  observer.observe(mark);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) introduce(); });
}

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
