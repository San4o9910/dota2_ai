// Pure trainer checks: no browser, network, account or model calls.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const root = new URL('../services/video/narma_video/static/', import.meta.url);
const source = await readFile(new URL('practice.js', root), 'utf8');
const { validatePracticeCatalog, createPracticeSession, filterPracticeScenarios } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const payload = JSON.parse(await readFile(new URL('practice-scenarios.json', root), 'utf8'));
const catalog = validatePracticeCatalog(payload);
assert.equal(new Set(Object.values(payload.positionGoals)).size, 5);
for (const difficulty of ['foundations', 'application', 'advanced']) {
  const openingDecisions = [];
  for (const position of [1, 2, 3, 4, 5]) {
    for (const draw of [0, .5, .999999]) {
      const session = createPracticeSession(catalog, { position, difficulty }, () => draw);
      assert.ok(session);
      assert.equal(session.questions.length, 5);
      assert.deepEqual(session.questions[0].positions, [position], 'A selected role must actually receive its own decision, independently of shuffle.');
      assert.ok(session.questions.every(question => question.positions.includes(position) && question.difficulty === difficulty));
      assert.equal(new Set(session.questions.map(question => question.id)).size, 5);
    }
    const [question] = createPracticeSession(catalog, { position, difficulty }, () => .5).questions;
    openingDecisions.push(question.question + JSON.stringify(question.choices));
    if (difficulty === 'advanced') assert.ok(question.variation, 'Every advanced role decision must support reconsidering changed conditions.');
  }
  assert.equal(new Set(openingDecisions).size, 5, 'Roles must change the decision and answers, beyond labels.');
}
for (const position of [1, 2, 3, 4, 5]) {
  for (const difficulty of ['foundations', 'application', 'advanced']) {
    for (const topic of ['lane', 'map', 'items', 'fights']) {
      const filters = { position, difficulty, topic };
      const eligible = filterPracticeScenarios(catalog, filters);
      const session = createPracticeSession(catalog, filters, () => .5);
      if (!eligible.length) assert.equal(session, null, 'An empty selection must not silently widen to another role or level.');
      else {
        assert.equal(session.questions.length, Math.min(5, eligible.length));
        assert.ok(session.questions.every(question => eligible.includes(question)));
      }
    }
  }
}
console.log(`Role-specific trainer: ${catalog.length} scenarios, all five positions and three levels verified.`);
