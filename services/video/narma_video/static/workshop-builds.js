// Public Steam Workshop guides, attributed to their authors. These helpers do
// not rank builds or invent match statistics, roles, items or purchase timings.
export const WORKSHOP_PHASES = Object.freeze({
  starting_items: 'Стартовые предметы', early_items: 'Ранняя игра', core_items: 'Основные покупки',
  extension_items: 'Развитие сборки', situational_items: 'По ситуации', luxury_items: 'Поздняя игра',
});
const roles = new Set(['core', 'support', 'offlane', 'unknown']);
const states = new Set(['current_patch', 'patch_changed', 'review_due', 'stale', 'unknown']);
const safeText = (value, max) => typeof value === 'string' && value.length > 0 && value.length <= max;
const validItem = item => item && /^[a-z0-9_]{1,80}$/.test(item.id) && safeText(item.name, 160);

export function workshopSourceURL(value, id) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname === 'steamcommunity.com' && !url.username && !url.password && !url.port
      && url.pathname.replace(/\/$/, '') === '/sharedfiles/filedetails' && url.searchParams.get('id') === id ? url.href : '';
  } catch { return ''; }
}

export function validateWorkshopFeed(payload) {
  if (!payload || payload.schema_version !== 'narma.workshop-builds.v1' || !Array.isArray(payload.guides) || payload.guides.length > 1500
      || !payload.coverage || !['heroes', 'total_heroes', 'guides', 'current_patch_guides'].every(key => Number.isInteger(payload.coverage[key]) && payload.coverage[key] >= 0)
      || !Array.isArray(payload.errors) || typeof payload.stale !== 'boolean') throw new Error('Invalid workshop feed');
  const ids = new Set();
  const guides = payload.guides.filter(guide => {
    if (!guide || !/^\d{1,20}$/.test(guide.workshop_id) || guide.id !== `steam-${guide.workshop_id}` || ids.has(guide.id)
        || !/^[a-z0-9_]{1,80}$/.test(guide.hero_slug) || !safeText(guide.hero_name, 160) || !safeText(guide.author, 160)
        || !workshopSourceURL(guide.source_url, guide.workshop_id) || !roles.has(guide.role) || !states.has(guide.status) || !/^\d{1,2}\.\d{1,3}[a-z]?$/.test(guide.source_patch)
        || !Array.isArray(guide.positions) || guide.positions.length > 5 || new Set(guide.positions).size !== guide.positions.length
        || guide.positions.some(position => !Number.isInteger(position) || position < 1 || position > 5)
        || typeof guide.position_exact !== 'boolean') return false;
    if (guide.unknown_item_ids !== undefined && (!Array.isArray(guide.unknown_item_ids) || guide.unknown_item_ids.length > 512 || guide.unknown_item_ids.some(id => typeof id !== 'string' || !/^[a-z0-9_]{1,80}$/.test(id)) || new Set(guide.unknown_item_ids).size !== guide.unknown_item_ids.length)) return false;
    if (guide.position_exact && (!Number.isInteger(guide.position) || guide.positions.length !== 1 || guide.positions[0] !== guide.position)) return false;
    if ((guide.role === 'core' && guide.positions.some(position => position > 3)) || (guide.role === 'support' && guide.positions.some(position => position < 4))) return false;
    if (!Object.keys(WORKSHOP_PHASES).every(key => Array.isArray(guide[key]) && guide[key].length <= 24 && guide[key].every(validItem))) return false;
    if (!Array.isArray(guide.final_items) || guide.final_items.length > 6 || !guide.final_items.every(validItem) || new Set(guide.final_items.map(item => item.id)).size !== guide.final_items.length) return false;
    const sourceItems = new Set(Object.keys(WORKSHOP_PHASES).flatMap(key => guide[key].map(item => item.id)));
    if (guide.final_items.some(item => !sourceItems.has(item.id))) return false;
    ids.add(guide.id);
    return true;
  }).map(guide => ({ ...guide, source: 'workshop', title: safeText(guide.title, 400) ? guide.title : `${guide.hero_name} · ${guide.author}`, position: guide.position_exact ? guide.position : null }));
  return { ...payload, guides };
}

export function workshopMatchesPosition(guide, position) {
  return !position || guide.positions.includes(Number(position));
}

export function workshopRoleLabel(guide) {
  if (guide.position_exact) return `Позиция ${guide.position}`;
  if (guide.role === 'support') return 'Поддержка · позиции 4–5';
  if (guide.role === 'offlane') return 'Офлейн · позиция 3';
  if (guide.role === 'core') return 'Коры · позиции 1–3';
  return 'Позиция не указана автором';
}

export function workshopFreshness(guide, feed, now = Date.now()) {
  let state = guide.status;
  const incompleteItems = Array.isArray(guide.unknown_item_ids) && guide.unknown_item_ids.length > 0;
  const fetched = Date.parse(guide.fetched_at || '');
  const updated = Date.parse(guide.source_updated_at || '');
  if (state === 'stale' || !Number.isFinite(fetched) || fetched > now + 300000 || now - fetched >= 24 * 60 * 60 * 1000) state = 'stale';
  else if (!/^\d{1,2}\.\d{1,3}[a-z]?$/.test(feed.latest_patch || '')) state = 'unknown';
  else if (feed.latest_patch && guide.source_patch !== feed.latest_patch) state = 'patch_changed';
  else if (state === 'current_patch' && (!Number.isFinite(updated) || updated > now + 300000 || now - updated > 30 * 24 * 60 * 60 * 1000)) state = 'review_due';
  if (state === 'current_patch' && incompleteItems) state = 'review_due';
  const patch = guide.source_patch || 'не указан';
  let text = {
    current_patch: `Автор указал текущий патч ${patch}. Сверяй выбор предметов с условиями своего матча.`,
    patch_changed: `Сборка автора для ${patch}; текущий известный патч — ${feed.latest_patch || 'не подтверждён'}. После обновления нужна повторная проверка.`,
    review_due: incompleteItems ? 'В руководстве есть новые или недоступные предметы. Список покупок показан не полностью; перед игрой сверь оригинал автора.' : `Указан патч ${patch}, но автор давно не обновлял руководство. Сборку нужно перепроверить.`,
    stale: `Сохранена сборка для ${patch}. Проверка обновлений источника задерживается.`,
    unknown: `Автор указал патч ${patch}. Соответствие текущей версии игры сейчас не подтверждено.`,
  }[state] || 'Не удалось подтвердить актуальность сборки.';
  if (incompleteItems && state !== 'review_due') text += ' Часть предметов автора не удалось распознать: показан неполный список. Сверь оригинал перед покупкой.';
  return { state, stale: state !== 'current_patch', text, incompleteItems };
}

export function sortWorkshopGuides(guides, feed, position, now = Date.now()) {
  const stateOrder = { current_patch: 0, review_due: 1, unknown: 2, patch_changed: 3, stale: 4 };
  const selectedPosition = Number(position);
  const hasPosition = Number.isInteger(selectedPosition) && selectedPosition >= 1 && selectedPosition <= 5;
  const keys = new Map(guides.map(guide => {
    const updated = Date.parse(guide.source_updated_at || '');
    return [guide, {
      freshness: stateOrder[workshopFreshness(guide, feed, now).state] ?? 5,
      exact: hasPosition && guide.position_exact === true && guide.position === selectedPosition ? 0 : 1,
      updated: Number.isFinite(updated) && updated <= now + 300000 ? updated : -Infinity,
    }];
  }));
  return guides.slice().sort((one, two) => {
    const a = keys.get(one), b = keys.get(two);
    if (a.freshness !== b.freshness) return a.freshness - b.freshness;
    if (a.exact !== b.exact) return a.exact - b.exact;
    if (a.updated !== b.updated) return a.updated > b.updated ? -1 : 1;
    return String(one.id) < String(two.id) ? -1 : String(one.id) > String(two.id) ? 1 : 0;
  });
}
