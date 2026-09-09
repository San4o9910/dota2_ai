/* Original, fictional teaching situations. No replay or model inference is used. */
const TOPICS = Object.freeze({ all: 'Все темы', map: 'Карта', lane: 'Линия', items: 'Предметы', fights: 'Драка' });
const POSITIONS = Object.freeze({ all: 'Все позиции', 1: '1 · Керри', 2: '2 · Мид', 3: '3 · Офлейн', 4: '4 · Поддержка', 5: '5 · Полная поддержка' });
const DIFFICULTIES = Object.freeze({ foundations: 'Основы', application: 'Применение', advanced: 'Сложные решения' });
const SESSION_LENGTHS = Object.freeze({ 5: '5 решений · короткая практика', 10: '10 решений · обычная серия', 15: '15 решений · подробная практика' });
const LEVEL_DESCRIPTIONS = Object.freeze({
  foundations: 'Одна задача и явные условия: добивание, доступность предмета, позиция и безопасный маршрут. Начни здесь, если ещё трудно назвать причину решения.',
  application: 'Сравни две полезные задачи: подготовку волны, время команды, расход телепорта и продолжение контроля. Объясни, чем платишь за выбранный вариант.',
  advanced: 'Учти цену информации, распределение давления, выкуп и закрывающееся окно. После ответа появится новое условие: проверь, нужно ли менять план.',
});
const STORAGE_KEY = 'narma.practice.v1.history';
const VERSION = 'narma.practice.v1';
const mounts = new WeakMap();
const bounded = (value, max) => typeof value === 'string' && value.trim().length > 0 && value.length <= max;
const ident = value => typeof value === 'string' && /^[a-z0-9-]{1,64}$/.test(value);
const difficultyOf = value => Object.hasOwn(DIFFICULTIES, value) ? value : 'foundations';
const lengthOf = value => Object.hasOwn(SESSION_LENGTHS, value) ? Number(value) : 10;
const questionCount = count => `${count} ${count % 100 >= 11 && count % 100 <= 14 ? 'вопросов' : count % 10 === 1 ? 'вопрос' : count % 10 >= 2 && count % 10 <= 4 ? 'вопроса' : 'вопросов'}`;

function validateChoices(value) {
  if (!Array.isArray(value.choices) || value.choices.length < 3 || value.choices.length > 4 || new Set(value.choices.map(choice => choice?.id)).size !== value.choices.length) throw new Error('Invalid choices');
  for (const choice of value.choices) if (!choice || !ident(choice.id) || !bounded(choice.text, 400) || !bounded(choice.explanation, 900)) throw new Error('Invalid choice');
  if (!value.choices.some(choice => choice.id === value.correctChoiceId)) throw new Error('Invalid answer');
}

export function validatePracticeCatalog(value) {
  if (!value || value.version !== VERSION || !Array.isArray(value.scenarios) || !value.scenarios.length || value.scenarios.length > 500) throw new Error('Invalid practice catalog');
  if (value.positionGoals !== undefined && (!value.positionGoals || typeof value.positionGoals !== 'object' || [1, 2, 3, 4, 5].some(position => !bounded(value.positionGoals[position], 700)))) throw new Error('Invalid position goals');
  const ids = new Set();
  for (const scenario of value.scenarios) {
    if (!scenario || !ident(scenario.id) || ids.has(scenario.id) || !Object.hasOwn(TOPICS, scenario.topic) || scenario.topic === 'all') throw new Error('Invalid practice scenario');
    ids.add(scenario.id);
    if (!Object.hasOwn(DIFFICULTIES, scenario.difficulty)) throw new Error('Invalid difficulty');
    if (!Array.isArray(scenario.positions) || !scenario.positions.length || scenario.positions.length > 5 || scenario.positions.some(p => !Number.isInteger(p) || p < 1 || p > 5) || new Set(scenario.positions).size !== scenario.positions.length) throw new Error('Invalid positions');
    for (const key of ['title', 'question', 'signal', 'action', 'why', 'exception', 'reviewQuestion']) if (!bounded(scenario[key], key === 'title' ? 120 : 700)) throw new Error('Invalid practice text');
    if (!Array.isArray(scenario.context) || scenario.context.length < 2 || scenario.context.length > 6 || scenario.context.some(line => !bounded(line, 700))) throw new Error('Invalid context');
    validateChoices(scenario);
    for (const [key, limit] of [['briefing', 1600], ['common_trap', 1000], ['takeaway', 500]]) {
      if (scenario[key] !== undefined && !bounded(scenario[key], limit)) throw new Error('Invalid teaching text');
    }
    for (const key of ['decision_steps', 'worked_example']) {
      if (scenario[key] !== undefined && (!Array.isArray(scenario[key]) || scenario[key].length < 2 || scenario[key].length > 6 || scenario[key].some(step => !bounded(step, 900)))) throw new Error('Invalid teaching steps');
    }
    if (scenario.counterfactual !== undefined && (!scenario.counterfactual || ['change', 'decision'].some(key => !bounded(scenario.counterfactual[key], 1000)))) throw new Error('Invalid counterfactual');
    if (scenario.replay_task !== undefined && (!scenario.replay_task || ['setup', 'action', 'success'].some(key => !bounded(scenario.replay_task[key], 900)))) throw new Error('Invalid replay task');
    if (scenario.variation !== undefined) {
      const variation = scenario.variation;
      if (!variation || !bounded(variation.question, 700) || !Array.isArray(variation.context) || variation.context.length < 1 || variation.context.length > 4 || variation.context.some(line => !bounded(line, 700))) throw new Error('Invalid variation');
      validateChoices(variation);
    }
    for (const key of ['hero', 'item']) if (scenario[key] && (!/^[a-z0-9_]{1,80}$/.test(scenario[key].id) || !bounded(scenario[key].name, 100))) throw new Error('Invalid artwork');
  }
  return value.scenarios;
}

export function filterPracticeScenarios(scenarios, filters = {}) {
  const topic = Object.hasOwn(TOPICS, filters.topic) ? filters.topic : 'all';
  const position = Object.hasOwn(POSITIONS, filters.position) ? String(filters.position) : 'all';
  const difficulty = difficultyOf(filters.difficulty);
  return scenarios.filter(scenario => difficultyOf(scenario.difficulty) === difficulty && (topic === 'all' || scenario.topic === topic) && (position === 'all' || scenario.positions.includes(Number(position))));
}

export function createPracticeSession(scenarios, filters = {}, random = Math.random, options = {}) {
  const questions = filterPracticeScenarios(scenarios, filters).slice();
  if (!questions.length) return null;
  for (let i = questions.length - 1; i > 0; i -= 1) {
    const draw = random();
    const j = Math.floor(Math.max(0, Math.min(0.999999999, Number.isFinite(draw) ? draw : 0)) * (i + 1));
    [questions[i], questions[j]] = [questions[j], questions[i]];
  }
  // Recent ids are newest first. Use unseen situations first, then the least
  // recently practised. Role-specific decisions lead within each group. A small
  // selection stays small; another role or difficulty must never fill it out.
  const recent = [...new Set((Array.isArray(options.recentScenarioIds) ? options.recentScenarioIds : []).filter(ident))];
  const recency = new Map(recent.map((id, index) => [id, recent.length - index]));
  const selectedRole = String(filters.position) !== 'all' && Object.hasOwn(POSITIONS, filters.position);
  questions.sort((one, two) => (recency.get(one.id) || 0) - (recency.get(two.id) || 0) || (selectedRole ? one.positions.length - two.positions.length : 0));
  const requestedLength = lengthOf(filters.length);
  return { questions: questions.slice(0, requestedLength), requestedLength, availableCount: questions.length, index: 0, answers: [], variations: {}, rationales: {}, status: 'answering' };
}

export function answerPracticeQuestion(session, choiceId) {
  if (!session || session.status !== 'answering') return session;
  const scenario = session.questions[session.index];
  if (!scenario.choices.some(choice => choice.id === choiceId)) return session;
  return { ...session, status: 'review', answers: [...session.answers, { scenarioId: scenario.id, choiceId, correct: choiceId === scenario.correctChoiceId }] };
}

export function advancePracticeSession(session) {
  if (!session || session.status !== 'review') return session;
  return session.index + 1 === session.questions.length
    ? { ...session, status: 'complete' }
    : { ...session, index: session.index + 1, status: 'answering' };
}

export function revealPracticeVariation(session) {
  if (!session || session.status !== 'review') return session;
  const scenario = session.questions[session.index];
  if (!scenario.variation || session.variations?.[scenario.id]) return session;
  return { ...session, variations: { ...session.variations, [scenario.id]: { status: 'answering' } } };
}

export function answerPracticeVariation(session, choiceId) {
  if (!session || session.status !== 'review') return session;
  const scenario = session.questions[session.index];
  const variation = scenario.variation;
  if (!variation || session.variations?.[scenario.id]?.status !== 'answering' || !variation.choices.some(choice => choice.id === choiceId)) return session;
  return { ...session, variations: { ...session.variations, [scenario.id]: { status: 'review', choiceId, correct: choiceId === variation.correctChoiceId } } };
}

export function validatePracticeHistory(value) {
  if (!value || value.version !== VERSION || !Array.isArray(value.sessions) || value.sessions.length > 20) return [];
  return value.sessions.filter(entry => entry && bounded(entry.id, 100) && typeof entry.completedAt === 'string' && entry.completedAt.length <= 40 && Number.isFinite(Date.parse(entry.completedAt)) && Number.isInteger(entry.total) && entry.total >= 1 && entry.total <= 15 && Number.isInteger(entry.correct) && entry.correct >= 0 && entry.correct <= entry.total && Object.hasOwn(TOPICS, entry.topic) && Object.hasOwn(POSITIONS, entry.position) && (entry.difficulty === undefined || Object.hasOwn(DIFFICULTIES, entry.difficulty))).slice(-20).map(entry => ({
    id: entry.id, completedAt: entry.completedAt, total: entry.total, correct: entry.correct,
    topic: entry.topic, position: String(entry.position), difficulty: difficultyOf(entry.difficulty), length: lengthOf(entry.length),
    // Older history did not record ids. Keep its scores without guessing which
    // questions were seen. Ignore malformed optional metadata, not the history.
    questionIds: Array.isArray(entry.questionIds) && entry.questionIds.length === entry.total && entry.questionIds.every(ident) && new Set(entry.questionIds).size === entry.total ? entry.questionIds : [],
    topicResults: Array.isArray(entry.topicResults) ? entry.topicResults.filter(result => result && Object.hasOwn(TOPICS, result.topic) && result.topic !== 'all' && Number.isInteger(result.total) && result.total > 0 && result.total <= entry.total && Number.isInteger(result.correct) && result.correct >= 0 && result.correct <= result.total).slice(0, 4) : [],
  }));
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function button(text, handler, className = 'practice-button') {
  const node = element('button', className, text);
  node.type = 'button';
  node.addEventListener('click', handler);
  return node;
}
function artwork(value, kind) {
  const wrapper = element('span', `practice-art practice-art--${kind}`);
  const picture = element('img');
  picture.alt = '';
  picture.width = kind === 'hero' ? 96 : 64;
  picture.height = kind === 'hero' ? 54 : 48;
  picture.loading = 'lazy';
  picture.referrerPolicy = 'no-referrer';
  picture.src = `https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/${kind === 'hero' ? 'heroes' : 'items'}/${value.id}.png`;
  picture.addEventListener('error', () => { picture.remove(); wrapper.classList.add('practice-art--fallback'); wrapper.textContent = value.name; }, { once: true });
  wrapper.append(picture);
  wrapper.setAttribute('aria-hidden', 'true');
  return wrapper;
}
function focusHeading(node) {
  node.tabIndex = -1;
  node.focus();
}

function choiceFeedback(choices, choiceId, stage) {
  const review = element('div', 'practice-choice-review');
  const selected = choices.find(choice => choice.id === choiceId);
  const selectedReview = element('div', 'practice-selected-review');
  const explanation = element('p', '', selected.explanation);
  explanation.dataset.practiceSelectedExplanation = stage;
  selectedReview.append(element('strong', '', 'О твоём выборе'), explanation);
  const alternatives = element('details', 'practice-alternatives');
  alternatives.dataset.practiceAlternatives = stage;
  alternatives.append(element('summary', '', 'Разбор других вариантов'));
  const contents = element('div', 'practice-alternatives-content');
  choices.forEach((choice, index) => {
    if (choice.id === choiceId) return;
    const row = element('div', 'practice-alternative');
    row.append(element('strong', '', `${String.fromCharCode(65 + index)} · ${choice.text}`), element('p', '', choice.explanation));
    contents.append(row);
  });
  alternatives.append(contents);
  review.append(selectedReview, alternatives);
  return review;
}

function teachingDetails(title, contents, kind) {
  const details = element('details', 'practice-teaching');
  details.dataset.practiceTeaching = kind;
  details.append(element('summary', '', title));
  const body = element('div', 'practice-teaching-content');
  body.append(...contents);
  details.append(body);
  // Keep one deeper explanation open at a time, including browsers without
  // support for the native details[name] accordion.
  details.addEventListener('toggle', () => {
    if (!details.open) return;
    details.parentElement?.querySelectorAll(':scope > details[data-practice-teaching]').forEach(other => { if (other !== details) other.open = false; });
  });
  return details;
}

function teachingSteps(steps) {
  const list = element('ol', 'practice-teaching-steps');
  steps.forEach(step => list.append(element('li', '', step)));
  return list;
}

function replayTask(task) {
  const checklist = element('dl', 'practice-replay-task');
  for (const [title, value] of [['Где проверить', task.setup], ['Что сделать', task.action], ['По чему судить', task.success]]) {
    const row = element('div');
    row.append(element('dt', '', title), element('dd', '', value));
    checklist.append(row);
  }
  return checklist;
}

export function mountPractice(container) {
  if (!(container instanceof HTMLElement)) throw new TypeError('Practice needs a container');
  mounts.get(container)?.();
  const aborter = new AbortController();
  let disposed = false;
  let catalog = [];
  let positionGoals = {};
  let session = null;
  let sessionId = '';
  let recorded = false;
  const query = new URLSearchParams(globalThis.location?.search || '');
  let filters = {
    topic: Object.hasOwn(TOPICS, query.get('topic')) ? query.get('topic') : 'all',
    position: Object.hasOwn(POSITIONS, query.get('position')) ? query.get('position') : 'all',
    difficulty: difficultyOf(query.get('difficulty')),
    length: String(lengthOf(query.get('length'))),
  };
  let history = [];
  let storageAvailable = true;
  let loadAttempt = 0;
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && stored.length <= 100000) history = validatePracticeHistory(JSON.parse(stored));
  } catch { storageAvailable = false; }

  container.classList.add('practice');
  const cleanup = () => { disposed = true; aborter.abort(); mounts.delete(container); };
  mounts.set(container, cleanup);

  function writeHistory() {
    if (!storageAvailable) return;
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: VERSION, sessions: history })); }
    catch { storageAvailable = false; }
  }
  function begin(source = catalog) {
    const chosenSource = Array.isArray(source) ? source : catalog;
    const recentScenarioIds = chosenSource === catalog ? history.slice().reverse().flatMap(entry => entry.questionIds || []) : [];
    session = createPracticeSession(chosenSource, filters, Math.random, { recentScenarioIds });
    if (!session) return;
    sessionId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    recorded = false;
    renderQuestion(true);
  }
  function resetFilters() {
    filters = { ...filters, topic: 'all', position: 'all' };
    syncFilterUrl();
    renderSetup();
    container.querySelector('[data-practice-start]')?.focus();
  }
  function caption(text) { return element('p', 'practice-eyebrow', text); }
  function selectFilter(label, key, values) {
    const wrapper = element('label', 'practice-filter');
    wrapper.append(element('span', 'practice-filter-label', label));
    const select = element('select');
    select.dataset.practiceFilter = key;
    for (const [value, title] of Object.entries(values)) {
      const option = element('option', '', title);
      option.value = value;
      option.selected = value === filters[key];
      select.append(option);
    }
    select.addEventListener('change', () => { filters[key] = select.value; syncFilterUrl(); updateAvailability(); });
    wrapper.append(select);
    return wrapper;
  }
  function syncFilterUrl() {
    const url = new URL(globalThis.location.href);
    for (const [key, value] of Object.entries(filters)) {
      if (value === 'all' || (key === 'difficulty' && value === 'foundations') || (key === 'length' && value === '10')) url.searchParams.delete(key);
      else url.searchParams.set(key, value);
    }
    globalThis.history.replaceState(globalThis.history.state, '', url);
  }
  function updateAvailability() {
    const count = filterPracticeScenarios(catalog, filters).length;
    const length = lengthOf(filters.length);
    const status = container.querySelector('[data-practice-availability]');
    if (!status) return;
    status.textContent = count === 0 ? 'Для этого сочетания пока нет ситуаций. Сбрось фильтры, чтобы начать.'
      : count < length ? `В подборке для выбранных позиции, темы и уровня — ${questionCount(count)}. Серия будет короче выбранных ${length}; в ней только задания по твоим условиям.`
      : `В подборке — ${questionCount(count)}. В серии — ${length} без повторов; сначала ситуации, которых ещё не было в сохранённой истории.`;
    const start = container.querySelector('[data-practice-start]');
    start.disabled = count === 0;
    start.textContent = count ? `Начать серию · ${questionCount(Math.min(length, count))}` : 'Нет подходящих ситуаций';
    container.querySelector('[data-practice-reset-filters]').hidden = filters.topic === 'all' && filters.position === 'all';
    const levelNote = container.querySelector('[data-practice-level-note]');
    if (levelNote) levelNote.textContent = LEVEL_DESCRIPTIONS[filters.difficulty];
    const roleNote = container.querySelector('[data-practice-role-note]');
    if (roleNote) roleNote.textContent = positionGoals[filters.position] || 'Выбери свою позицию: изменятся приоритеты на линии, перемещения и первые задания серии. Общие принципы остаются там, где они применимы к выбранной роли.';
    container.querySelector('.practice-history')?.replaceWith(historyPanel());
  }
  function historyPanel() {
    const box = element('aside', 'practice-history');
    box.append(caption('На этом устройстве'));
    if (!storageAvailable) {
      box.append(element('h3', '', 'Можно тренироваться без сохранения'), element('p', '', 'Браузер не разрешил сохранить историю. Ответы и объяснения работают; после закрытия страницы история этой серии может исчезнуть.'));
      return box;
    }
    const matching = history.filter(entry => (filters.position === 'all' || entry.position === filters.position) && entry.difficulty === filters.difficulty && (filters.topic === 'all' || entry.topic === filters.topic));
    const latest = matching.at(-1);
    box.append(element('h3', '', latest ? 'Последняя серия по твоему выбору' : 'Практика с разбором решений'));
    if (latest) {
      box.append(element('p', 'practice-history-score', `${latest.correct} из ${latest.total}`));
      box.append(element('p', '', `Выбраны действия, соответствующие условиям задания. ${new Date(latest.completedAt).toLocaleDateString('ru-RU')} · ${DIFFICULTIES[latest.difficulty]} · ${TOPICS[latest.topic]} · ${POSITIONS[latest.position]}`));
      const topicResults = (latest.topicResults || []).filter(value => value.correct < value.total).sort((one, two) => one.correct / one.total - two.correct / two.total);
      if (topicResults.length) box.append(element('p', 'practice-history-focus', `Вернись к теме «${TOPICS[topicResults[0].topic]}»: в последней серии ${topicResults[0].correct} из ${topicResults[0].total} решений соответствовали условиям.`));
      box.append(element('p', 'practice-fine', `Сохранено серий: ${history.length}. Здесь хранятся последние 20 завершённых серий, только в этом браузере.`));
      box.append(button('Очистить историю на устройстве', () => {
        history = [];
        try { localStorage.removeItem(STORAGE_KEY); } catch { storageAvailable = false; }
        renderSetup();
        const note = container.querySelector('[data-practice-history-notice]');
        if (note) note.textContent = storageAvailable ? 'История на этом устройстве очищена.' : 'Браузер не разрешил очистить сохранённую историю.';
      }, 'practice-text-button'));
    } else {
      box.append(element('p', '', 'Выбери 5, 10 или 15 решений. После каждого — логика выбора, разбор альтернатив и задание для собственной игры. Для сложных ситуаций есть новое условие: проверь, умеешь ли ты менять план.'));
      if (history.length) box.append(element('p', 'practice-fine', 'Серий для выбранных позиции, темы и уровня ещё нет. Другие результаты сохранены.'));
    }
    const notice = element('p', 'practice-fine');
    notice.dataset.practiceHistoryNotice = '';
    notice.setAttribute('role', 'status');
    box.append(notice);
    return box;
  }
  function renderSetup() {
    session = null;
    const layout = element('div', 'practice-setup');
    const card = element('section', 'practice-card practice-intro');
    card.append(caption('Сигнал → действие → почему'), element('h2', '', 'Что ты сделаешь дальше?'));
    card.append(element('p', 'practice-lead', 'Тренируй ход мысли: что известно, какая задача важнее и чем ты рискуешь. Сначала прими решение, затем разберись в альтернативах и проверь вывод в своей игре.'));
    const steps = element('ol', 'practice-steps');
    for (const [number, title, text] of [['01', 'Заметь сигнал', 'Что известно до решения?'], ['02', 'Выбери действие', 'Что доступно прямо сейчас?'], ['03', 'Проверь причину', 'Почему этот выбор подходит?']]) {
      const li = element('li');
      li.append(element('span', 'practice-step-number', number), element('strong', '', title), element('span', '', text));
      steps.append(li);
    }
    card.append(steps);
    const filterRow = element('div', 'practice-filters');
    filterRow.append(selectFilter('Уровень заданий', 'difficulty', DIFFICULTIES), selectFilter('Тема', 'topic', TOPICS), selectFilter('Твоя позиция', 'position', POSITIONS), selectFilter('Длина серии', 'length', SESSION_LENGTHS));
    card.append(filterRow);
    const roleNote = element('p', 'practice-level-note');
    roleNote.dataset.practiceRoleNote = '';
    roleNote.setAttribute('role', 'status');
    card.append(roleNote);
    const levelNote = element('p', 'practice-level-note');
    levelNote.dataset.practiceLevelNote = '';
    levelNote.setAttribute('role', 'status');
    card.append(levelNote, element('p', 'practice-fine', 'Уровень выбираешь ты. Все три доступны сразу: результат викторины не определяет твой MMR и не закрывает следующий уровень.'));
    const available = element('p', 'practice-availability');
    available.dataset.practiceAvailability = '';
    available.setAttribute('role', 'status');
    card.append(available);
    const actions = element('div', 'practice-actions');
    const start = button('Начать серию', begin, 'practice-button practice-button--primary');
    start.dataset.practiceStart = '';
    const reset = button('Сбросить фильтры', resetFilters, 'practice-text-button');
    reset.dataset.practiceResetFilters = '';
    actions.append(start, reset);
    card.append(actions);
    card.append(element('p', 'practice-fine', 'Это авторские вымышленные ситуации, а не анализ твоих матчей. Лучший ответ определяется только указанными условиями. Результат серии не измеряет MMR или уровень игры.'));
    layout.append(card, historyPanel());
    container.replaceChildren(layout);
    updateAvailability();
  }
  function renderQuestion(moveFocus = false) {
    const current = session;
    const scenario = current.questions[current.index];
    const answered = current.status === 'review';
    const answer = current.answers.at(-1);
    const shell = element('div', 'practice-play');
    const toolbar = element('div', 'practice-toolbar');
    const position = `Вопрос ${current.index + 1} из ${current.questions.length}`;
    const progressLabel = element('span', '', position);
    progressLabel.dataset.practiceProgress = '';
    toolbar.append(progressLabel, button('Изменить выбор', renderSetup, 'practice-text-button'));
    const progress = element('progress', 'practice-progress');
    progress.max = current.questions.length;
    progress.value = current.answers.length;
    progress.setAttribute('aria-label', 'Количество ответов в серии');
    shell.append(toolbar, progress);
    const card = element('section', 'practice-card practice-question');
    card.dataset.scenarioId = scenario.id;
    const identity = element('div', 'practice-identity');
    if (scenario.hero) identity.append(artwork(scenario.hero, 'hero'));
    const labels = element('div');
    labels.append(caption(`${DIFFICULTIES[scenario.difficulty]} · ${TOPICS[scenario.topic]} · ${filters.position === 'all' ? scenario.positions.map(position => POSITIONS[position]).join(', ') : POSITIONS[filters.position]}`));
    if (scenario.hero) labels.append(element('p', 'practice-hero-name', scenario.hero.name));
    identity.append(labels);
    if (scenario.item) {
      const item = element('span', 'practice-item');
      item.append(artwork(scenario.item, 'item'), element('span', '', scenario.item.name));
      identity.append(item);
    }
    card.append(identity);
    const heading = element('h2', '', scenario.title);
    card.append(heading);
    const conditions = element('ul', 'practice-conditions');
    scenario.context.forEach(line => conditions.append(element('li', '', line)));
    card.append(conditions);
    const question = element('h3', 'practice-choice-question', scenario.question);
    question.id = 'practice-choice-question';
    card.append(question);
    if (!answered) {
      const reflection = element('details', 'practice-reflection');
      reflection.append(element('summary', '', 'Сначала объясни себе решение · по желанию'));
      const label = element('label', 'practice-reflection-label');
      label.append(element('span', '', 'Какой факт решающий и при каком изменении ты выберешь другое действие?'));
      const input = element('textarea', 'practice-reflection-input');
      input.rows = 3;
      input.maxLength = 900;
      input.value = current.rationales?.[scenario.id] || '';
      input.dataset.practiceRationale = '';
      input.placeholder = 'Например: сначала проверю…, потому что… Если…, сменю план на…';
      input.addEventListener('input', () => { session.rationales = { ...session.rationales, [scenario.id]: input.value }; });
      label.append(input);
      reflection.append(label, element('p', 'practice-fine', 'Заметка нужна для сравнения с разбором. Она не оценивается автоматически и не сохраняется после выхода из серии.'));
      card.append(reflection);
    }
    const choices = element('div', 'practice-choices');
    choices.setAttribute('role', 'group');
    choices.setAttribute('aria-labelledby', question.id);
    scenario.choices.forEach((choice, index) => {
      const choiceButton = button('', () => {
        session = answerPracticeQuestion(session, choice.id);
        renderQuestion();
        focusHeading(container.querySelector('[data-practice-feedback-title]'));
      }, 'practice-choice');
      choiceButton.dataset.choiceId = choice.id;
      choiceButton.disabled = answered;
      choiceButton.append(element('span', 'practice-choice-letter', String.fromCharCode(65 + index)), element('span', 'practice-choice-text', choice.text));
      if (answered) {
        if (choice.id === scenario.correctChoiceId) {
          choiceButton.classList.add('practice-choice--correct');
          choiceButton.append(element('span', 'practice-choice-tag', 'Подходит по условиям'));
        }
        if (choice.id === answer.choiceId) {
          choiceButton.classList.add('practice-choice--selected');
          choiceButton.append(element('span', 'practice-choice-tag', 'Твой выбор'));
        }
      }
      choices.append(choiceButton);
    });
    card.append(choices);
    if (!answered) card.append(element('p', 'practice-fine', 'После выбора ответ фиксируется. Времени на размышление сколько угодно.'));
    shell.append(card);
    if (answered) {
      const feedback = element('section', 'practice-feedback');
      const feedbackTitle = element('h3', '', answer.correct ? 'Выбор подходит по условиям' : 'Есть лучше обоснованный вариант');
      feedbackTitle.dataset.practiceFeedbackTitle = '';
      feedbackTitle.setAttribute('role', 'status');
      feedback.append(feedbackTitle);
      if (scenario.briefing) feedback.append(element('p', 'practice-briefing', scenario.briefing));
      const reasoning = element('dl', 'practice-reasoning');
      for (const [term, text] of [['Сигнал', scenario.signal], ['Действие', scenario.action], ['Почему', scenario.why]]) {
        const row = element('div'); row.append(element('dt', '', term), element('dd', '', text)); reasoning.append(row);
      }
      feedback.append(reasoning);
      feedback.append(choiceFeedback(scenario.choices, answer.choiceId, 'main'));
      const deeper = element('div', 'practice-teaching-group');
      if (current.rationales?.[scenario.id]) deeper.append(teachingDetails('Сравни со своим объяснением', [element('p', 'practice-own-reason', current.rationales[scenario.id]), element('p', 'practice-fine', 'Какой важный сигнал ты учёл? Что пропустил? Разбор выше помогает проверить логику, но не оценивает твой текст.')], 'reflection'));
      if (scenario.decision_steps) deeper.append(teachingDetails('Как прийти к решению · по шагам', [teachingSteps(scenario.decision_steps)], 'steps'));
      if (scenario.worked_example) deeper.append(teachingDetails('Разобранный пример', [teachingSteps(scenario.worked_example)], 'example'));
      if (scenario.common_trap) deeper.append(teachingDetails('Почему легко ошибиться', [element('p', '', scenario.common_trap)], 'trap'));
      if (scenario.counterfactual) deeper.append(teachingDetails('Если изменить один факт', [element('h4', '', 'Что изменилось'), element('p', '', scenario.counterfactual.change), element('h4', '', 'Как изменится решение'), element('p', '', scenario.counterfactual.decision)], 'counterfactual'));
      if (deeper.childElementCount) feedback.append(deeper);
      feedback.append(element('p', 'practice-exception', `Когда решение изменится: ${scenario.exception}`));
      const transfer = element('div', 'practice-transfer');
      transfer.append(caption('Перенеси в свою игру'), element('p', '', scenario.takeaway || scenario.reviewQuestion));
      if (scenario.replay_task) transfer.append(teachingDetails('Задание для своего матча', [replayTask(scenario.replay_task)], 'replay'));
      feedback.append(transfer);
      if (scenario.variation) feedback.append(variationPanel(scenario));
      const next = button(current.index + 1 === current.questions.length ? 'Посмотреть итог' : 'Следующая ситуация', () => {
        session = advancePracticeSession(session);
        if (session.status === 'complete') renderResult(); else renderQuestion(true);
      }, 'practice-button practice-button--primary');
      next.dataset.practiceNext = '';
      feedback.append(next);
      shell.append(feedback);
    }
    container.replaceChildren(shell);
    if (moveFocus) focusHeading(heading);
  }
  function variationPanel(scenario) {
    const variation = scenario.variation;
    const state = session.variations?.[scenario.id];
    const section = element('section', 'practice-variation');
    section.dataset.practiceVariation = scenario.id;
    section.append(caption('Проверь гибкость решения'));
    const title = element('h4', '', 'Ситуация изменилась');
    title.dataset.practiceVariationTitle = '';
    section.append(title, element('p', 'practice-fine', 'Дополнительное решение. Оно не меняет счёт основной серии: задача — заметить, когда прежний план перестаёт подходить.'));
    if (!state) {
      const reveal = button('Открыть новое условие', () => {
        session = revealPracticeVariation(session);
        renderQuestion();
        focusHeading(container.querySelector('[data-practice-variation-title]'));
      });
      reveal.dataset.practiceVariationReveal = '';
      section.append(reveal);
      return section;
    }
    const conditions = element('ul', 'practice-conditions');
    variation.context.forEach(line => conditions.append(element('li', '', line)));
    const question = element('p', 'practice-variation-question', variation.question);
    question.id = 'practice-variation-question';
    section.append(conditions, question);
    const choices = element('div', 'practice-choices');
    choices.setAttribute('role', 'group');
    choices.setAttribute('aria-labelledby', question.id);
    variation.choices.forEach((choice, index) => {
      const choiceButton = button('', () => {
        session = answerPracticeVariation(session, choice.id);
        renderQuestion();
        focusHeading(container.querySelector('[data-practice-variation-feedback]'));
      }, 'practice-choice');
      choiceButton.dataset.variationChoice = choice.id;
      choiceButton.disabled = state.status === 'review';
      choiceButton.append(element('span', 'practice-choice-letter', String.fromCharCode(65 + index)), element('span', 'practice-choice-text', choice.text));
      if (state.status === 'review') {
        if (choice.id === variation.correctChoiceId) {
          choiceButton.classList.add('practice-choice--correct');
          choiceButton.append(element('span', 'practice-choice-tag', 'Подходит по новым условиям'));
        }
        if (choice.id === state.choiceId) {
          choiceButton.classList.add('practice-choice--selected');
          choiceButton.append(element('span', 'practice-choice-tag', 'Твой выбор'));
        }
      }
      choices.append(choiceButton);
    });
    section.append(choices);
    if (state.status === 'review') {
      const outcome = element('h4', '', state.correct ? 'Новые условия учтены' : 'План нужно пересмотреть');
      outcome.dataset.practiceVariationFeedback = '';
      outcome.setAttribute('role', 'status');
      section.append(outcome);
      section.append(choiceFeedback(variation.choices, state.choiceId, 'variation'));
    }
    return section;
  }
  function renderResult() {
    const score = session.answers.filter(answer => answer.correct).length;
    const topicResults = Object.keys(TOPICS).filter(topic => topic !== 'all').map(topic => {
      const answers = session.answers.filter(answer => session.questions.find(question => question.id === answer.scenarioId)?.topic === topic);
      return { topic, total: answers.length, correct: answers.filter(answer => answer.correct).length };
    }).filter(value => value.total);
    if (!recorded) {
      history = [...history, { id: sessionId, completedAt: new Date().toISOString(), total: session.questions.length, correct: score, ...filters, questionIds: session.questions.map(question => question.id), topicResults }].slice(-20);
      writeHistory();
      recorded = true;
    }
    const result = element('section', 'practice-card practice-result');
    result.dataset.practiceResult = '';
    result.append(caption('Серия завершена'));
    result.append(element('p', 'practice-fine', `${DIFFICULTIES[filters.difficulty]} · ${TOPICS[filters.topic]} · ${POSITIONS[filters.position]}`));
    const heading = element('h2', '', 'Теперь важнее объяснение');
    result.append(heading, element('p', 'practice-score', `${score} из ${session.questions.length}`));
    result.append(element('p', 'practice-lead', 'Ответов соответствуют условиям учебных ситуаций. Это результат этой серии, а не оценка твоего рейтинга или понимания всей игры.'));
    result.append(element('p', 'practice-fine', storageAvailable ? 'Серия сохранена на этом устройстве. В истории остаются последние 20 завершённых серий.' : 'История не сохранена: браузер ограничил хранилище. Разбор серии доступен, пока открыта эта страница.'));
    const recap = element('div', 'practice-recap');
    recap.append(element('h3', '', 'Возьми один фокус в следующую игру'));
    const firstMissed = session.answers.find(answer => !answer.correct);
    const focus = session.questions.find(scenario => scenario.id === firstMissed?.scenarioId) || session.questions[0];
    recap.append(element('p', '', focus.takeaway || focus.reviewQuestion));
    if (focus.replay_task) recap.append(replayTask(focus.replay_task));
    result.append(recap);
    const topics = element('div', 'practice-topic-results');
    topics.append(element('h3', '', 'Что показала эта серия'));
    const topicList = element('ul');
    for (const row of topicResults) topicList.append(element('li', '', `${TOPICS[row.topic]}: ${row.correct} из ${row.total} · ${row.correct < row.total ? 'вернись к объяснению ошибок' : 'проверь вывод в матче'}`));
    topics.append(topicList);
    result.append(topics);
    const list = element('div', 'practice-result-list');
    session.questions.forEach((scenario, index) => {
      const details = element('details', 'practice-result-row');
      const summary = element('summary');
      summary.append(element('span', '', `${index + 1}. ${scenario.title}`), element('span', session.answers[index].correct ? 'practice-result-state practice-result-state--correct' : 'practice-result-state', session.answers[index].correct ? 'Подходит' : 'Повторить смысл'));
      details.append(summary, element('p', '', `Твой выбор: ${scenario.choices.find(choice => choice.id === session.answers[index].choiceId).text}`), element('p', '', `Действие: ${scenario.action}`), element('p', '', `Почему: ${scenario.why}`), element('p', 'practice-fine', `Когда решение изменится: ${scenario.exception}`));
      list.append(details);
      if (scenario.decision_steps) details.append(teachingSteps(scenario.decision_steps));
      if (scenario.replay_task) details.append(replayTask(scenario.replay_task));
    });
    result.append(list);
    const actions = element('div', 'practice-actions');
    const retry = button('Новая серия', begin, 'practice-button practice-button--primary');
    retry.dataset.practiceRetry = '';
    actions.append(retry, button('Выбрать другую тему', renderSetup, 'practice-text-button'));
    const missedIds = new Set(session.answers.filter(answer => !answer.correct).map(answer => answer.scenarioId));
    const missed = session.questions.filter(scenario => missedIds.has(scenario.id));
    if (missed.length) {
      const repeat = button(`Вернуться к ошибкам · ${missed.length}`, () => begin(missed));
      repeat.dataset.practiceRepeatMissed = '';
      actions.append(repeat);
    }
    result.append(actions);
    container.replaceChildren(result);
    focusHeading(heading);
  }
  async function loadCatalog() {
    const attempt = ++loadAttempt;
    const loading = element('p', 'practice-loading', 'Загружаем учебные ситуации…');
    loading.setAttribute('role', 'status');
    container.replaceChildren(loading);
    const timeout = setTimeout(() => aborter.abort(), 20000);
    try {
      const response = await fetch(new URL('./practice-scenarios.json', import.meta.url), { credentials: 'same-origin', signal: aborter.signal });
      if (!response.ok) throw new Error('Catalog unavailable');
      const raw = await response.text();
      if (raw.length > 4 * 1024 * 1024) throw new Error('Catalog too large');
      const payload = JSON.parse(raw);
      catalog = validatePracticeCatalog(payload);
      positionGoals = payload.positionGoals || {};
      if (!disposed && attempt === loadAttempt) renderSetup();
    } catch {
      if (disposed || attempt !== loadAttempt) return;
      const error = element('section', 'practice-card');
      error.setAttribute('role', 'alert');
      error.append(element('h2', '', 'Не удалось загрузить ситуации'), element('p', '', 'Проверь соединение и попробуй ещё раз. История завершённых серий останется на этом устройстве.'));
      error.append(button('Попробовать ещё раз', () => mountPractice(container)));
      container.replaceChildren(error);
    } finally { clearTimeout(timeout); }
  }
  void loadCatalog();
  return cleanup;
}
