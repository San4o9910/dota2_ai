import { roleGuidance } from './role-guidance.js';
const page = document.querySelector('#page-content');
const paths = { '/': 'home', '/heroes': 'heroes', '/builds': 'builds', '/learn': 'learn', '/practice': 'practice', '/updates': 'updates' };
const route = paths[location.pathname.replace(/\/$/, '') || '/'] || 'home';
const attributes = { strength: 'Сила', agility: 'Ловкость', intelligence: 'Интеллект', universal: 'Универсальный' };
const categories = { patch: 'Обновление', event: 'Событие', news: 'Новости' };
const titles = { home: 'Играй осознаннее', heroes: 'Герои Dota 2', builds: 'Сборки и игровые задачи', learn: 'Обучение', practice: 'Тренажёр решений', updates: 'В мире Dota' };
const allowedLinks = new Set(['www.dota2.com', 'dota2.com', 'store.steampowered.com', 'steamcommunity.com', 'www.steamcommunity.com', 'bsjdota.com', 'prosettings.net', 'www.reddit.com', 'reddit.com', 'www.cybersport.ru', 'cybersport.ru']);
const imageHosts = new Set(['cdn.cloudflare.steamstatic.com', 'cdn.akamai.steamstatic.com', 'shared.akamai.steamstatic.com', 'clan.akamai.steamstatic.com', 'clan.cloudflare.steamstatic.com', 'shared.cloudflare.steamstatic.com', 'www.dota2.com', 'cdn.steamstatic.com', 'cdn.fastly.steamstatic.com', 'clan.fastly.steamstatic.com']);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const local = (path, params = {}) => { const query = new URLSearchParams(params).toString(); return `${path}${query ? `?${query}` : ''}`; };
const date = value => { const d = new Date(value); return value && !Number.isNaN(d.getTime()) ? d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' }) : 'Дата не указана'; };
function safeURL(value, images = false) {
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password && !url.port && (images ? imageHosts : allowedLinks).has(url.hostname) ? url.href : ''; } catch { return ''; }
}
function external(url, label, className = '') { const href = safeURL(url); return href ? `<a href="${esc(href)}" class="${esc(className)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>` : `<span>${esc(label)}</span>`; }
function heroImage(hero, loading = 'lazy') { const src = safeURL(hero.image_url, true); return src ? `<img src="${esc(src)}" alt="" loading="${loading}" width="256" height="144">` : ''; }
function sourceNote(data, noun = 'Данные') {
  const parsed = new Date(data.checked_at);
  const checked = data.checked_at && !Number.isNaN(parsed.getTime()) ? `Проверено ${parsed.toLocaleString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC', timeZoneName: 'short' })}` : 'Дата проверки недоступна';
  const state = data.refreshing ? 'Проверяем свежие публикации.' : data.stale && data.errors?.length ? 'Показываем сохранённую версию: свежие данные пока недоступны.' : data.stale ? 'Сохранённая версия ожидает обновления.' : '';
  const href = Array.isArray(data.heroes) ? 'https://www.dota2.com/heroes' : 'https://www.dota2.com/news';
  return `<div class="source-note${data.stale ? ' is-stale' : ''}"><p>${esc(noun)}: ${external(href, 'Dota 2 / Valve')}. ${esc(checked)}. ${esc(state)}</p>${data.stale || data.refreshing ? '<button class="source-refresh" data-refresh-content type="button">Обновить данные</button>' : ''}</div>`;
}
function bindRefresh(container, reload) { container.querySelectorAll('[data-refresh-content]').forEach(button => button.addEventListener('click', async () => { button.disabled = true; button.textContent = 'Обновляем…'; await reload(); })); }

async function api(endpoint) {
  const response = await fetch(`/api/explore/${endpoint}`, { credentials: 'omit', headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(20000) });
  if (!response.ok) throw new Error('CONTENT_UNAVAILABLE');
  return response.json();
}
function errorPanel(container, retry, text = 'Не удалось загрузить этот раздел. Попробуй ещё раз.') {
  container.innerHTML = `<div class="error-box"><p>${esc(text)}</p><button type="button" class="button">Попробовать снова</button></div>`;
  container.querySelector('button').addEventListener('click', retry);
}
function positionOptions(selected = '') { return [['', 'Все позиции'], ['1', '1 · Керри'], ['2', '2 · Мидер'], ['3', '3 · Офлейнер'], ['4', '4 · Поддержка'], ['5', '5 · Полная поддержка']].map(([value, label]) => `<option value="${value}"${String(selected) === value ? ' selected' : ''}>${label}</option>`).join(''); }
function imageFallbacks(container) {
  container.querySelectorAll('img').forEach(img => img.addEventListener('error', () => { img.removeAttribute('src'); img.hidden = true; }, { once: true }));
}
document.title = `${titles[route]} — Narma Vision`;
document.querySelector(`[data-route="${route}"]`)?.setAttribute('aria-current', 'page');

function home() {
  page.innerHTML = `<div class="home-lead"><section class="practice-feature" aria-labelledby="home-heading"><p class="eyebrow">Dota 2 · практика решений</p><h1 id="home-heading">Учись принимать<br>сильные решения в Dota.</h1><p class="muted">Куда пойти? Когда драться? Для чего покупать предмет? Разбирай игровые ситуации и переноси понятные действия в свои матчи.</p><div class="button-row"><a class="button primary" href="/practice">Начать тренировку <span aria-hidden="true">→</span></a><a class="button subtle" href="/learn">Открыть обучение</a></div><p class="feature-note"><span><i aria-hidden="true"></i>5 ситуаций за подход</span><span><i aria-hidden="true"></i>Разбор каждого ответа</span><span><i aria-hidden="true"></i>Без регистрации</span></p></section><aside class="home-news" id="home-news" aria-label="В мире Dota"><div class="section-heading"><h2 id="home-news-heading">В мире Dota</h2><a class="text-link" href="/updates">Все новости <span aria-hidden="true">→</span></a></div><p class="page-status" role="status">Загружаем новости Valve…</p></aside></div><section class="home-section" aria-labelledby="home-heroes-heading"><div class="section-heading"><div><h2 id="home-heroes-heading">Знай своего героя</h2><p>Найди героя и разберись в его задачах.</p></div><a class="text-link" href="/heroes">Все герои <span aria-hidden="true">→</span></a></div><div id="home-heroes" class="hero-strip"><p class="page-status" role="status">Загружаем героев…</p></div></section><div class="home-bottom"><section aria-labelledby="home-learning-heading"><div class="section-heading"><div><h2 id="home-learning-heading">От линии к пониманию игры</h2><p>Одна ступень. Одно действие. Проверка в своей игре.</p></div><a class="text-link" href="/learn">6 ступеней <span aria-hidden="true">→</span></a></div><div id="home-stages" class="stage-preview-list"><p class="page-status" role="status">Открываем упражнения…</p></div></section><aside class="personal-promo"><p class="eyebrow">Твои матчи</p><h2>У каждой цифры<br>есть игровой эпизод.</h2><p>Загрузи реплей, посмотри покупки, смерти и экономику своего героя. Выбери конкретное действие для следующей игры и отслеживай результат в пуле героев.</p><a class="button" href="/replays">Разобрать свой матч <span aria-hidden="true">↗</span></a><div class="personal-links"><a href="/hero-pool">Мой пул героев</a><a href="/my-learning">Моя практика</a></div></aside></div>`;
  const loadNews = async () => {
    const target = document.querySelector('#home-news');
    try {
      const data = await api('updates');
      const rows = (data.news || []).filter(n => safeURL(n.url)).slice(0, 3);
      target.innerHTML = `<div class="section-heading"><h2 id="home-news-heading">В мире Dota</h2><a class="text-link" href="/updates">Все новости →</a></div>${rows.map(n => `<a class="update-compact" href="${esc(safeURL(n.url))}" target="_blank" rel="noopener noreferrer"><div class="date-line"><span class="category-label">${esc(categories[n.category] || 'Новости')}</span><time datetime="${esc(n.published_at)}">${esc(date(n.published_at))}</time></div><h3>${esc(n.title)}</h3></a>`).join('') || '<p class="page-status">Пока нет доступных публикаций.</p>'}${sourceNote(data, 'Публикации')}`;
      bindRefresh(target, loadNews);
    } catch { errorPanel(target, loadNews, 'Новости Valve сейчас недоступны. Герои и тренировки работают отдельно.'); }
  };
  const loadHeroes = async () => {
    const target = document.querySelector('#home-heroes');
    try {
      const data = await api('heroes');
      const preferred = ['juggernaut', 'viper', 'pudge', 'crystalmaiden', 'earthshaker', 'invoker', 'windranger'];
      const heroes = preferred.map(slug => data.heroes?.find(h => h.slug.replace(/_/g, '') === slug)).filter(Boolean);
      for (const hero of data.heroes || []) { if (heroes.length >= 7) break; if (!heroes.some(h => h.id === hero.id)) heroes.push(hero); }
      target.innerHTML = heroes.map(hero => `<a class="hero-tile" href="${esc(local('/heroes', { hero: hero.slug }))}">${heroImage(hero)}<span>${esc(hero.display_name)}</span></a>`).join('');
      imageFallbacks(target);
    } catch { errorPanel(target, loadHeroes, 'Библиотека героев временно недоступна.'); }
  };
  const loadLessons = async () => {
    const target = document.querySelector('#home-stages');
    try { const data = await api('learning'); target.innerHTML = (data.stages || []).map(stage => `<a class="stage-preview" href="${esc(local('/learn', { stage: stage.id }))}"><span class="stage-number">${esc(String(stage.order).padStart(2, '0'))}</span><div><h3>${esc(stage.title)}</h3><p>${esc(stage.description)}</p></div><span class="arrow" aria-hidden="true">→</span></a>`).join(''); }
    catch { errorPanel(target, loadLessons, 'Не удалось открыть учебную программу.'); }
  };
  return Promise.allSettled([loadNews(), loadHeroes(), loadLessons()]);
}

async function heroes() {
  page.innerHTML = `<div class="page-heading"><div><p class="eyebrow">Библиотека Dota 2</p><h1>Герои</h1><p>Найди своего героя. Посмотри его атрибут и сложность, открой способности на официальной странице.</p></div><a href="/hero-pool" class="text-link">Мой пул героев ↗</a></div><div id="hero-library"><p class="page-status" role="status">Загружаем библиотеку…</p></div>`;
  const container = document.querySelector('#hero-library');
  const load = async () => {
    try {
      const data = await api('heroes');
      const all = [...(data.heroes || [])].sort((a, b) => a.display_name.localeCompare(b.display_name));
      let query = new URLSearchParams(location.search).get('q') || '';
      let attribute = new URLSearchParams(location.search).get('attribute') || '';
      if (!attributes[attribute]) attribute = '';
      let selected = all.find(h => h.slug === new URLSearchParams(location.search).get('hero')) || all.find(h => h.slug === 'viper') || all[0];
      container.innerHTML = `<div class="toolbar"><div class="field search-field"><label for="hero-search">Поиск по имени</label><input id="hero-search" type="search" autocomplete="off" maxlength="80" placeholder="Например, Viper" value="${esc(query)}"></div><div><p class="toolbar-label">Основной атрибут</p><div class="attribute-filters" aria-label="Атрибут героя"><button class="filter-button" type="button" data-attribute="" aria-pressed="${!attribute}">Все</button>${Object.entries(attributes).map(([key, label]) => `<button class="filter-button" type="button" data-attribute="${key}" aria-pressed="${key === attribute}"><i class="attribute-dot ${key}" aria-hidden="true"></i>${label}</button>`).join('')}</div></div></div><div class="catalog-layout"><div class="hero-catalog"><p class="hero-result-heading" id="hero-count" role="status" aria-live="polite"></p><div id="hero-grid" class="hero-grid"></div></div><aside id="hero-inspector" class="hero-inspector" aria-label="Выбранный герой"></aside></div>${sourceNote(data, 'Герои')}`;
      const inspector = document.querySelector('#hero-inspector');
      const sync = () => { const params = {}; if (query) params.q = query; if (attribute) params.attribute = attribute; if (selected) params.hero = selected.slug; history.replaceState(null, '', local('/heroes', params)); };
      const select = hero => {
        selected = hero;
        if (!hero) { inspector.hidden = true; return; }
        inspector.hidden = false;
        inspector.innerHTML = `${heroImage(hero, 'eager')}<div class="inspector-body"><h2>${esc(hero.display_name)}</h2><dl class="inspector-facts"><div><dt>Основной атрибут</dt><dd><i class="attribute-dot ${esc(hero.attribute)}" aria-hidden="true"></i>${esc(attributes[hero.attribute] || 'Не указан')}</dd></div><div><dt>Сложность по Dota 2</dt><dd><span class="difficulty" aria-hidden="true">${'◆'.repeat(Math.min(3, Math.max(1, Number(hero.complexity) || 1)))}</span>${esc(hero.complexity)} из 3</dd></div></dl>${external(hero.official_url, 'Способности и герой ↗', 'button primary')}<a class="button subtle" href="${esc(local('/builds', { hero: hero.slug }))}">Сборки и игровые задачи →</a><p>Способности и изменения героя смотри у Valve. Личные результаты на герое появятся в твоём пуле после разбора матчей.</p></div>`;
        document.querySelectorAll('[data-hero]').forEach(b => b.setAttribute('aria-pressed', String(Number(b.dataset.hero) === hero.id)));
        imageFallbacks(inspector); sync();
      };
      const render = () => {
        const term = query.trim().toLocaleLowerCase();
        const filtered = all.filter(h => (!attribute || h.attribute === attribute) && `${h.display_name} ${h.slug} ${h.name}`.toLocaleLowerCase().includes(term));
        document.querySelector('#hero-count').innerHTML = `<strong>${filtered.length}</strong> из ${all.length} героев`;
        const grid = document.querySelector('#hero-grid');
        grid.innerHTML = filtered.length ? filtered.map(h => `<button class="hero-choice" type="button" data-hero="${h.id}" aria-pressed="${selected?.id === h.id}" aria-label="${esc(h.display_name)}">${heroImage(h)}<span>${esc(h.display_name)}</span></button>`).join('') : '<div class="empty-message"><p>Такой герой не найден. Проверь имя или сбрось фильтры.</p><button type="button" class="button" id="reset-hero-search">Сбросить фильтры</button></div>';
        grid.querySelectorAll('[data-hero]').forEach(b => b.addEventListener('click', () => select(all.find(h => h.id === Number(b.dataset.hero)))));
        grid.querySelector('#reset-hero-search')?.addEventListener('click', () => { query = ''; attribute = ''; document.querySelector('#hero-search').value = ''; document.querySelectorAll('[data-attribute]').forEach(b => b.setAttribute('aria-pressed', String(!b.dataset.attribute))); render(); });
        imageFallbacks(grid); sync();
      };
      document.querySelector('#hero-search').addEventListener('input', event => { query = event.target.value; render(); });
      document.querySelectorAll('[data-attribute]').forEach(b => b.addEventListener('click', () => { attribute = b.dataset.attribute; document.querySelectorAll('[data-attribute]').forEach(other => other.setAttribute('aria-pressed', String(other === b))); render(); }));
      render(); select(selected); bindRefresh(container, load);
    } catch { errorPanel(container, load, 'Не удалось загрузить героев. Попробуй ещё раз.'); }
  };
  return load();
}

async function learn() {
  const params = new URLSearchParams(location.search);
  let position = /^[1-5]$/.test(params.get('position') || '') ? params.get('position') : '';
  let selectedStage = params.get('stage') || '';
  let serial = 0;
  page.innerHTML = `<div class="page-heading"><div><p class="eyebrow">Библиотека обучения</p><h1>Понимать. Пробовать. Проверять.</h1><p>Шесть ступеней от линии до самостоятельного разбора. Выбери позицию и одно действие, которое сможешь проверить в следующей игре.</p></div><a href="/my-learning" class="text-link">Моя практика ↗</a></div><div class="toolbar"><div class="field"><label for="learn-position">Твоя позиция</label><select id="learn-position">${positionOptions(position)}</select></div><p class="learning-toolbar-note" id="learn-position-note">Выбери позицию, чтобы увидеть упражнения для своей линии и роли. Общие игровые решения доступны всем.</p></div><div id="learning-library"><p class="page-status" role="status">Загружаем упражнения…</p></div>`;
  const container = document.querySelector('#learning-library');
  const load = async () => {
    const request = ++serial;
    container.setAttribute('aria-busy', 'true');
    container.replaceChildren(Object.assign(document.createElement('p'), { className: 'page-status', textContent: 'Подбираем упражнения для выбранной позиции…' }));
    try {
      const data = await api(`learning${position ? `?position=${position}` : ''}`);
      if (request !== serial) return;
      document.querySelector('#learn-position-note').textContent = data.role_context ? `План для позиции «${data.role_context.label}». Задачи, действия и проверка результата ниже учитывают эту роль.` : 'Общие принципы доступны всем. Выбери позицию, чтобы открыть конкретные действия для своей роли.';
      const stages = data.stages || [];
      if (!stages.some(s => s.id === selectedStage)) selectedStage = stages.find(s => (data.exercises || []).some(e => e.stage_id === s.id))?.id || stages[0]?.id;
      container.innerHTML = `<div class="learning-layout"><nav class="stage-nav" aria-label="Ступени обучения">${stages.map(s => `<button class="stage-button" type="button" data-stage="${esc(s.id)}" aria-pressed="${s.id === selectedStage}"><span>${esc(String(s.order).padStart(2, '0'))}</span><span>${esc(s.title)}</span></button>`).join('')}</nav><section id="lesson-content" aria-label="Упражнения выбранной ступени"></section></div><p class="source-note">${esc(data.source_note)}</p>`;
      const render = () => {
        const stage = stages.find(s => s.id === selectedStage);
        if (!stage) return;
        history.replaceState(null, '', local('/learn', { stage: selectedStage, ...(position ? { position } : {}) }));
        document.querySelectorAll('[data-stage]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.stage === selectedStage)));
        const exercises = (data.exercises || []).filter(e => e.stage_id === selectedStage);
        document.querySelector('#lesson-content').innerHTML = `<div class="lesson-stage-intro"><p class="eyebrow">Ступень ${esc(stage.order)} из ${stages.length}</p><h2>${esc(stage.title)}</h2><p>${esc(stage.description)}</p></div>${exercises.length ? exercises.map(e => `<article class="lesson-card" data-exercise="${esc(e.id)}"><h3>${esc(e.title)}</h3><p class="lesson-question">${esc(e.decision_question)}</p><p class="lesson-copy">${esc(e.mini_lesson)}</p><div class="lesson-action"><h4>Попробуй в игре</h4><p>${esc(e.action)}</p></div><div class="lesson-action"><h4>Упражнение</h4><p>${esc(e.drill)}</p></div><div class="lesson-action"><h4>Как проверить результат</h4><p>${esc(e.measurement)}</p></div><details><summary>Почему это работает и когда менять решение</summary><p>${esc(e.why)}</p><p><strong>Исключение.</strong> ${esc(e.exception)}</p></details><details><summary>Источники методики</summary><ul class="lesson-sources">${(e.source_refs || []).map(id => (data.sources || []).find(s => s.id === id)).filter(Boolean).map(s => `<li>${external(s.url, `${s.title} ↗`)}</li>`).join('')}</ul></details></article>`).join('') : '<div class="lesson-card"><h3>У каждой позиции своя работа на линии</h3><p class="lesson-copy">Выбери свою позицию вверху. Керри, мидер и офлейнер начнут с точности добиваний; поддержка — с выбора полезного действия для своей линии.</p><button id="choose-learning-position" class="button choose-position-button" type="button">Выбрать позицию ↑</button></div>'}<div class="lesson-end"><p>Потренируй выбор в коротких ситуациях. Затем проверь действие в своём матче.</p><a href="${esc(local('/practice', position ? { position } : {}))}" class="button">К тренажёру →</a></div>`;
        document.querySelector('#choose-learning-position')?.addEventListener('click', () => { const select = document.querySelector('#learn-position'); select.scrollIntoView({ block: 'center' }); select.focus(); });
      };
      document.querySelectorAll('[data-stage]').forEach(b => b.addEventListener('click', () => { selectedStage = b.dataset.stage; render(); }));
      const guidance = roleGuidance(data.role_context); if (guidance) container.prepend(guidance);
      render();
    } catch { if (request === serial) errorPanel(container, load, 'Не удалось открыть упражнения. Попробуй ещё раз.'); }
    finally { if (request === serial) container.setAttribute('aria-busy', 'false'); }
  };
  document.querySelector('#learn-position').addEventListener('change', event => { position = event.target.value; load(); });
  return load();
}

async function updates() {
  page.innerHTML = `<div class="page-heading"><div><p class="eyebrow">Публикации Valve</p><h1>В мире Dota</h1><p>Обновления, события и новости из официальных публикаций. Открой материал, чтобы увидеть подробности и условия события.</p></div>${external('https://www.dota2.com/news', 'Все публикации Dota 2 ↗', 'text-link')}</div><div id="updates-content"><p class="page-status" role="status">Загружаем публикации…</p></div>`;
  const container = document.querySelector('#updates-content');
  const load = async () => {
    try {
      const data = await api('updates');
      let selected = new URLSearchParams(location.search).get('category') || '';
      if (!categories[selected]) selected = '';
      const patch = data.latest_patch;
      container.innerHTML = `${patch && safeURL(patch.url) ? `<a class="patch-banner" href="${esc(safeURL(patch.url))}" target="_blank" rel="noopener noreferrer"><div><span>Последний патч в проверенном источнике</span><strong>Обновление ${esc(patch.version)}</strong><span>${esc(date(patch.published_at))} · Изменения героев и предметов</span></div><span aria-hidden="true">↗</span></a>` : ''}<div class="updates-header-extra attribute-filters" aria-label="Тип публикации"><button class="filter-button" type="button" data-category="" aria-pressed="${!selected}">Все публикации</button>${Object.entries(categories).map(([key, label]) => `<button class="filter-button" type="button" data-category="${key}" aria-pressed="${selected === key}">${label}</button>`).join('')}</div><p id="news-count" class="hero-result-heading" role="status" aria-live="polite"></p><div id="news-grid" class="news-grid"></div>${sourceNote(data, 'Источник')}`;
      const render = () => {
        const rows = (data.news || []).filter(n => safeURL(n.url) && (!selected || n.category === selected));
        history.replaceState(null, '', local('/updates', selected ? { category: selected } : {}));
        document.querySelector('#news-count').textContent = `Публикаций: ${rows.length}`;
        document.querySelector('#news-grid').innerHTML = rows.length ? rows.map(n => `<a class="news-card" href="${esc(safeURL(n.url))}" target="_blank" rel="noopener noreferrer">${safeURL(n.image_url, true) ? `<img src="${esc(safeURL(n.image_url, true))}" width="640" height="360" alt="" loading="lazy">` : ''}<div class="news-card-content"><div class="date-line"><span class="category-label">${esc(categories[n.category] || 'Новости')}</span><time datetime="${esc(n.published_at)}">${esc(date(n.published_at))}</time></div><h2>${esc(n.title)}</h2><span class="external-label">Читать у Valve ↗</span></div></a>`).join('') : '<p class="empty-message">В текущей подборке нет публикаций этого типа.</p>';
        imageFallbacks(document.querySelector('#news-grid'));
      };
      document.querySelectorAll('[data-category]').forEach(b => b.addEventListener('click', () => { selected = b.dataset.category; document.querySelectorAll('[data-category]').forEach(other => other.setAttribute('aria-pressed', String(other === b))); render(); }));
      render(); bindRefresh(container, load);
    } catch { errorPanel(container, load, 'Официальные публикации сейчас недоступны. Попробуй загрузить их ещё раз.'); }
  };
  return load();
}

let practiceCleanup = null;
window.addEventListener('pagehide', event => { if (!event.persisted) practiceCleanup?.(); });
async function practice() {
  practiceCleanup?.();
  practiceCleanup = null;
  page.innerHTML = `<div class="page-heading"><div><p class="eyebrow">Практика Dota 2</p><h1>Тренажёр решений</h1><p>Прочитай ситуацию, выбери действие и разбери причину. Пять вопросов помогут найти тему для практики в игре.</p></div><a href="/learn" class="text-link">Библиотека упражнений →</a></div><section id="practice-root" aria-label="Тренировка игровых решений"><p class="page-status" role="status">Открываем тренажёр…</p></section>`;
  const root = document.querySelector('#practice-root');
  try { const { mountPractice } = await import('/assets/practice.js'); practiceCleanup = mountPractice(root); }
  catch { errorPanel(root, practice, 'Не удалось открыть тренажёр. Попробуй ещё раз.'); }
}

async function builds() {
  const { mountBuilds } = await import('/assets/builds.js');
  await mountBuilds(page);
}

try { await ({ home, heroes, builds, learn, updates, practice }[route])(); }
catch { errorPanel(page, () => location.reload()); }
finally { page.setAttribute('aria-busy', 'false'); }
