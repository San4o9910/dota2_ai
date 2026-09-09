// Pure trainer checks: no browser, network, account or model calls.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const root = new URL('../services/video/narma_video/static/', import.meta.url);
const source = await readFile(new URL('practice.js', root), 'utf8');
const { validatePracticeCatalog, createPracticeSession, filterPracticeScenarios, validatePracticeHistory, answerPracticeQuestion, advancePracticeSession, revealPracticeVariation, answerPracticeVariation } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const payload = JSON.parse(await readFile(new URL('practice-scenarios.json', root), 'utf8'));
const catalog = validatePracticeCatalog(payload);
assert.equal(new Set(Object.values(payload.positionGoals)).size, 5);
for (const difficulty of ['foundations', 'application', 'advanced']) {
  const openingDecisions = [];
  for (const position of [1, 2, 3, 4, 5]) {
    for (const draw of [0, .5, .999999]) {
      const session = createPracticeSession(catalog, { position, difficulty }, () => draw);
      assert.ok(session);
      assert.equal(session.questions.length, Math.min(10, filterPracticeScenarios(catalog, { position, difficulty }).length));
      assert.ok(session.questions.length >= 5, 'Each role and depth needs enough distinct decisions to practise.');
      assert.deepEqual(session.questions[0].positions, [position], 'A selected role must actually receive its own decision, independently of shuffle.');
      assert.ok(session.questions.every(question => question.positions.includes(position) && question.difficulty === difficulty));
      assert.equal(new Set(session.questions.map(question => question.id)).size, session.questions.length);
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
      for (const length of [5, 10, 15]) {
        const session = createPracticeSession(catalog, { ...filters, length }, () => .5);
        if (!eligible.length) assert.equal(session, null, 'An empty selection must not silently widen to another role or level.');
        else {
          assert.equal(session.questions.length, Math.min(length, eligible.length));
          assert.equal(session.requestedLength, length);
          assert.equal(session.availableCount, eligible.length);
          assert.ok(session.questions.every(question => eligible.includes(question)));
          assert.equal(new Set(session.questions.map(question => question.id)).size, session.questions.length);
        }
      }
    }
  }
}

// History controls repetition, but must never broaden the user's selection.
for (const difficulty of ['foundations', 'application', 'advanced']) {
  for (const position of [1, 2, 3, 4, 5]) {
    const filters = { position, difficulty, length: 5 };
    const eligible = filterPracticeScenarios(catalog, filters);
    const first = createPracticeSession(catalog, filters, () => .5);
    const recentScenarioIds = first.questions.map(question => question.id);
    const second = createPracticeSession(catalog, filters, () => .5, { recentScenarioIds });
    const unseen = eligible.filter(question => !recentScenarioIds.includes(question.id));
    const repeated = second.questions.filter(question => recentScenarioIds.includes(question.id));
    assert.equal(repeated.length, Math.max(0, second.questions.length - unseen.length), 'Only exhausted matching content permits a recent repeat.');
    assert.ok(second.questions.slice(0, Math.min(unseen.length, second.questions.length)).every(question => !recentScenarioIds.includes(question.id)));
    assert.ok(second.questions.every(question => question.positions.includes(position) && question.difficulty === difficulty));
  }
}
const eligible = filterPracticeScenarios(catalog, { difficulty: 'foundations' });
const seenAll = eligible.map(question => question.id);
const oldestFirst = createPracticeSession(catalog, { difficulty: 'foundations', length: 5 }, () => .5, { recentScenarioIds: seenAll });
assert.deepEqual(oldestFirst.questions.map(question => question.id), seenAll.slice(-5).reverse(), 'When the pool is exhausted, revisit the oldest questions first.');
const noMatchingRole = catalog.filter(question => !question.positions.includes(5));
assert.equal(createPracticeSession(noMatchingRole, { position: 5 }), null);
assert.equal(createPracticeSession(catalog, { length: 999 }).requestedLength, 10);
const baseHistory = { id: 'legacy', completedAt: '2026-09-09T12:00:00Z', total: 5, correct: 3, position: '5', topic: 'all' };
const longHistory = { ...baseHistory, id: 'long-series', total: 15, correct: 10, difficulty: 'application', length: 15, questionIds: Array.from({ length: 15 }, (_, index) => `test-${index}`) };
const stored = validatePracticeHistory({ version: 'narma.practice.v1', sessions: [baseHistory, longHistory, { ...longHistory, id: 'bad-size', total: 16 }, { ...baseHistory, id: 'bad-ids', questionIds: ['<script>'] }] });
assert.equal(stored.length, 3);
assert.equal(stored[0].difficulty, 'foundations');
assert.deepEqual(stored[0].questionIds, []);
assert.deepEqual(stored[1].questionIds, longHistory.questionIds);
assert.deepEqual(stored[2].questionIds, []);
let session = createPracticeSession(catalog, { difficulty: 'advanced', length: 5 }, () => .5);
const question = session.questions[0];
assert.equal(advancePracticeSession(session), session);
assert.equal(answerPracticeQuestion(session, 'missing-answer'), session);
session = answerPracticeQuestion(session, question.correctChoiceId);
assert.equal(session.answers.length, 1);
assert.equal(answerPracticeQuestion(session, question.correctChoiceId), session);
if (question.variation) {
  session = revealPracticeVariation(session);
  session = answerPracticeVariation(session, question.variation.correctChoiceId);
  assert.equal(session.answers.length, 1);
  assert.equal(session.variations[question.id].correct, true);
  assert.equal(answerPracticeVariation(session, question.variation.correctChoiceId), session);
}
assert.equal(advancePracticeSession(session).index, 1);
const richer = structuredClone(payload);
const exemplar = richer.scenarios[0];
exemplar.briefing = 'Сначала выбери задачу, затем проверь доступные ресурсы.';
exemplar.decision_steps = ['Проверь положение волны.', 'Сравни безопасные варианты.'];
exemplar.counterfactual = { change: 'Союзник уходит с линии.', decision: 'Пересмотри доступный размен.' };
exemplar.replay_task = { setup: 'Найди похожий эпизод.', action: 'Останови реплей до решения.', success: 'Объясни свой следующий шаг.' };
if (exemplar.choices.length === 3) exemplar.choices.push({ id: 'extra-choice', text: 'Дополнительное действие.', explanation: 'Условия для него не выполнены.' });
assert.doesNotThrow(() => validatePracticeCatalog(richer));
exemplar.counterfactual = { change: 'Новые условия без решения.' };
assert.throws(() => validatePracticeCatalog(richer), /counterfactual/);
console.log(`Trainer verified: ${catalog.length} scenarios, five positions, three levels, 5/10/15-question sessions, repeat spacing and legacy history.`);
