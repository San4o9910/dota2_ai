// Public source contract checks. No browser, live provider or model calls.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../services/video/narma_video/static/workshop-builds.js', import.meta.url), 'utf8');
const { validateWorkshopFeed, workshopMatchesPosition, workshopRoleLabel, workshopFreshness, workshopSourceURL, sortWorkshopGuides } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const now = Date.parse('2026-09-09T12:00:00Z');
const guide = {
  id: 'steam-12345', workshop_id: '12345', hero_slug: 'abaddon', hero_name: 'Abaddon', title: 'Abaddon support',
  author: 'Guide author', source_url: 'https://steamcommunity.com/sharedfiles/filedetails/?id=12345',
  position: null, positions: [4, 5], position_exact: false, role: 'support',
  source_patch: '7.41e', source_updated_at: '2026-09-08T12:00:00Z', fetched_at: '2026-09-09T11:00:00Z', status: 'current_patch',
  starting_items: [{ id: 'tango', name: 'Tango' }], early_items: [{ id: 'arcane_boots', name: 'Arcane Boots' }],
  core_items: [{ id: 'force_staff', name: 'Force Staff' }], extension_items: [{ id: 'lotus_orb', name: 'Lotus Orb' }],
  situational_items: [], luxury_items: [], final_items: [{ id: 'arcane_boots', name: 'Arcane Boots' }, { id: 'force_staff', name: 'Force Staff' }],
};
const payload = { schema_version: 'narma.workshop-builds.v1', checked_at: '2026-09-09T11:00:00Z', latest_patch: '7.41e', stale: false,
  coverage: { heroes: 1, total_heroes: 127, guides: 1, current_patch_guides: 1 }, guides: [guide], errors: [] };
const parsed = validateWorkshopFeed(payload);
assert.equal(parsed.guides.length, 1);
assert.equal(parsed.guides[0].source, 'workshop');
assert.equal(parsed.guides[0].position, null);
assert.equal(parsed.guides[0].final_items.length, 2, 'Partial source inventories must remain partial.');
assert.equal(workshopMatchesPosition(guide, '1'), false);
assert.equal(workshopMatchesPosition(guide, '4'), true);
assert.equal(workshopMatchesPosition(guide, '5'), true);
assert.match(workshopRoleLabel(guide), /4–5/);
assert.equal(workshopFreshness(guide, payload, now).state, 'current_patch');
assert.equal(workshopFreshness(guide, { ...payload, latest_patch: '7.42' }, now).state, 'patch_changed');
assert.equal(workshopFreshness(guide, { ...payload, latest_patch: null }, now).state, 'unknown');
assert.equal(workshopFreshness({ ...guide, fetched_at: '2026-09-08T11:00:00Z' }, payload, now).state, 'stale');
assert.equal(workshopFreshness({ ...guide, source_updated_at: '2026-08-01T12:00:00Z' }, payload, now).state, 'review_due');
assert.equal(workshopFreshness({ ...guide, source_updated_at: '2027-01-01T12:00:00Z' }, payload, now).state, 'review_due');
const exact = { ...guide, position: 5, positions: [5], position_exact: true };
assert.equal(validateWorkshopFeed({ ...payload, guides: [exact] }).guides.length, 1);
assert.equal(workshopMatchesPosition(exact, 4), false);
assert.equal(workshopRoleLabel(exact), 'Позиция 5');
assert.equal(validateWorkshopFeed({ ...payload, guides: [{ ...guide, role: 'core', positions: [4] }] }).guides.length, 0);
assert.equal(validateWorkshopFeed({ ...payload, guides: [{ ...exact, positions: [4, 5] }] }).guides.length, 0);
assert.equal(validateWorkshopFeed({ ...payload, guides: [{ ...guide, final_items: [{ id: 'rapier', name: 'Divine Rapier' }] }] }).guides.length, 0, 'Unattributed items cannot be silently added.');
assert.equal(validateWorkshopFeed({ ...payload, guides: [guide, guide] }).guides.length, 1);
assert.equal(workshopSourceURL('javascript:alert(1)', '12345'), '');
assert.equal(workshopSourceURL('https://steamcommunity.com/sharedfiles/filedetails/?id=999', '12345'), '');
assert.equal(workshopSourceURL('https://steamcommunity.com.evil.test/sharedfiles/filedetails/?id=12345', '12345'), '');
assert.throws(() => validateWorkshopFeed({ ...payload, coverage: { heroes: 'all' } }));

// New item ids must never disappear behind a current-patch badge. Preserve
// known purchases, surface the incomplete source, and keep stronger stale or
// changed-patch states instead of masking them with a generic review label.
const incompleteGuide = { ...guide, unknown_item_ids: ['new_patch_item'] };
const incomplete = validateWorkshopFeed({ ...payload, guides: [incompleteGuide] });
assert.equal(incomplete.guides.length, 1);
assert.deepEqual(incomplete.guides[0].core_items, guide.core_items);
assert.deepEqual(incomplete.guides[0].unknown_item_ids, ['new_patch_item']);
assert.equal(workshopFreshness(incompleteGuide, payload, now).state, 'review_due');
assert.equal(workshopFreshness(incompleteGuide, payload, now).incompleteItems, true);
assert.match(workshopFreshness(incompleteGuide, payload, now).text, /не полностью/);
assert.equal(incomplete.guides.filter(row => workshopFreshness(row, payload, now).state === 'current_patch').length, 0);
assert.equal(workshopFreshness(incompleteGuide, { ...payload, latest_patch: '7.42' }, now).state, 'patch_changed');
assert.match(workshopFreshness(incompleteGuide, { ...payload, latest_patch: '7.42' }, now).text, /неполный список/);
assert.equal(workshopFreshness({ ...incompleteGuide, fetched_at: '2026-09-08T11:00:00Z' }, payload, now).state, 'stale');
assert.equal(workshopFreshness(incompleteGuide, { ...payload, latest_patch: null }, now).state, 'unknown');
assert.equal(validateWorkshopFeed({ ...payload, guides: [{ ...guide, unknown_item_ids: ['<invalid>'] }] }).guides.length, 0);
assert.equal(validateWorkshopFeed({ ...payload, guides: [{ ...guide, unknown_item_ids: ['new_patch_item', 'new_patch_item'] }] }).guides.length, 0);

// Current-patch candidates lead by default, independent of author/catalog
// order. Exact selected role beats a broad role within the same freshness.
const olderPatch = { ...guide, id: 'steam-100', source_patch: '7.41d', status: 'patch_changed' };
const currentBroad = { ...guide, id: 'steam-200' };
const currentExact = { ...exact, id: 'steam-300', source_updated_at: '2026-09-07T12:00:00Z' };
const input = [olderPatch, currentBroad, currentExact];
const ordered = sortWorkshopGuides(input, payload, '5', now);
assert.deepEqual(ordered.map(row => row.id), ['steam-300', 'steam-200', 'steam-100']);
assert.deepEqual(input.map(row => row.id), ['steam-100', 'steam-200', 'steam-300'], 'Sorting must not mutate the source snapshot.');
assert.equal(sortWorkshopGuides([{ ...olderPatch, ...{ position: 5, positions: [5], position_exact: true } }, currentBroad], payload, '5', now)[0].id, 'steam-200', 'Current broad-role guidance precedes an outdated exact-role guide.');
assert.equal(sortWorkshopGuides([currentExact, currentBroad], payload, '', now)[0].id, 'steam-200', 'With no role selected, more recent author updates lead.');
const offline = { ...payload, latest_patch: null, stale: true };
assert.equal(sortWorkshopGuides([currentExact, currentBroad], offline, '', now)[0].id, 'steam-200');
assert.ok(sortWorkshopGuides([currentExact, currentBroad], offline, '', now).every(row => workshopFreshness(row, offline, now).state !== 'current_patch'));
assert.equal(workshopFreshness({ ...currentBroad, status: 'stale' }, offline, now).state, 'stale', 'A known source failure remains stale when patch confirmation is unavailable.');
const tied = [{ ...currentBroad, id: 'steam-202' }, { ...currentBroad, id: 'steam-201' }];
assert.deepEqual(sortWorkshopGuides(tied, payload, '5', now).map(row => row.id), ['steam-201', 'steam-202']);
console.log('Workshop builds: source attribution, role filtering, partial inventories and patch freshness verified.');
