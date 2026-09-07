import assert from "node:assert/strict";
import test, { after } from "node:test";

import { database } from "./sqlite-d1.mjs";

import {
  createAnalysisVite,
  makeOpenDotaMatch,
  makeReport,
} from "./analysis-test-helpers.mjs";

const vite = await createAnalysisVite();
after(async () => vite.close());

const { D1AnalysisStore, decodeAnalysisCursor } = await vite.ssrLoadModule(
  "/lib/analyses/store.ts",
);
const { buildEvidenceBundle, normalizeOpenDotaMatch } = await vite.ssrLoadModule(
  "/lib/analysis/normalizer.ts",
);

function addUserAndGrant(sqlite, userId = "user-analysis", units = 1) {
  sqlite.prepare("INSERT INTO users (id, display_name) VALUES (?, ?)").run(userId, "Analyst");
  sqlite.prepare("INSERT INTO dota_player_profiles(user_id,account_id,nickname,source_match_id) VALUES (?,1000,?,?)").run(userId,"Test player","8963624400");
  for(const matchId of ["8963624400","8963624401","8963624402","8963624403"]) sqlite.prepare("INSERT INTO dota_match_targets(user_id,match_id,account_id,player_slot,hero_id) VALUES (?,?,1000,0,1)").run(userId,matchId);
  sqlite.prepare(`
    INSERT INTO entitlement_ledger (
      id, user_id, entry_type, resource, bucket_key, delta,
      idempotency_key, reference_type, reference_id
    ) VALUES (?, ?, 'grant', 'analysis', ?, ?, ?, 'manual_adjustment', ?)
  `).run(
    `grant-${userId}`,
    userId,
    `manual:${userId}`,
    units,
    `manual:${userId}:analysis`,
    userId,
  );
}

test("analysis creation reserves one entitlement atomically and replays safely", async () => {
  const { sqlite, d1 } = await database();
  addUserAndGrant(sqlite);
  const store = new D1AnalysisStore(d1);
  const input = {
    userId: "user-analysis",
    matchId: "8963624400",
    playerSlot: 0,
    idempotencyKey: "create:analysis:one",
  };

  const [first, concurrent] = await Promise.all([store.create(input), store.create(input)]);
  assert.deepEqual(new Set([first.outcome, concurrent.outcome]), new Set(["created", "replayed"]));
  assert.equal(first.job.id, concurrent.job.id);
  assert.equal(sqlite.prepare("SELECT COUNT(*) AS total FROM analysis_jobs").get().total, 1);
  assert.equal(
    sqlite.prepare("SELECT COUNT(*) AS total FROM entitlement_ledger WHERE entry_type = 'reserve'").get().total,
    1,
  );
  assert.equal(
    sqlite.prepare("SELECT SUM(delta) AS balance FROM entitlement_ledger WHERE user_id = ?").get(input.userId).balance,
    0,
  );

  const conflict = await store.create({ ...input, matchId: "8963624401" });
  assert.equal(conflict.outcome, "idempotency_conflict");
  const identityReplay = await store.create({ ...input, idempotencyKey: "create:analysis:two" });
  assert.equal(identityReplay.outcome, "replayed");
  const insufficient = await store.create({
    ...input,
    matchId: "8963624401",
    idempotencyKey: "create:analysis:three",
  });
  assert.equal(insufficient.outcome, "insufficient_entitlement");
  sqlite.close();
});

test("leases are exclusive and a terminal failure releases the exact bucket", async () => {
  const { sqlite, d1 } = await database();
  addUserAndGrant(sqlite);
  const store = new D1AnalysisStore(d1);
  const created = await store.create({
    userId: "user-analysis",
    matchId: "8963624400",
    playerSlot: 0,
    idempotencyKey: "create:analysis:lease",
  });
  assert.equal(created.outcome, "created");

  const [left, right] = await Promise.all([
    store.claimOwned("user-analysis", created.job.id),
    store.claimOwned("user-analysis", created.job.id),
  ]);
  const claimed = left.outcome === "claimed" ? left : right;
  const blocked = left.outcome === "claimed" ? right : left;
  assert.equal(claimed.outcome, "claimed");
  assert.equal(blocked.outcome, "busy");
  assert.deepEqual(
    await store.fail(claimed.claim, {
      code: "OPENAI_INVALID_RESPONSE",
      message: "AI-сервис вернул некорректный отчёт.",
      retryable: false,
    }),
    { outcome: "failed" },
  );

  const detail = await store.getOwned("user-analysis", created.job.id);
  assert.equal(detail.job.state, "failed");
  assert.equal(detail.job.failure.retryable, false);
  assert.equal(
    sqlite.prepare("SELECT SUM(delta) AS balance FROM entitlement_ledger WHERE user_id = ?").get("user-analysis").balance,
    1,
  );
  assert.equal((await store.claimOwned("user-analysis", created.job.id)).outcome, "terminal");
  const replayedTerminal = await store.create({
    userId: "user-analysis",
    matchId: "8963624400",
    playerSlot: 0,
    idempotencyKey: "create:analysis:lease",
  });
  assert.equal(replayedTerminal.outcome, "replayed");
  assert.equal(replayedTerminal.job.id, created.job.id);
  const freshAttempt = await store.create({
    userId: "user-analysis",
    matchId: "8963624400",
    playerSlot: 0,
    idempotencyKey: "create:analysis:lease:fresh",
  });
  assert.equal(freshAttempt.outcome, "rate_limited");
  sqlite.prepare("UPDATE analysis_jobs SET updated_at = datetime('now', '-16 minutes') WHERE id = ?").run(created.job.id);
  const afterCooldown = await store.create({ userId: "user-analysis", matchId: "8963624400", playerSlot: 0, idempotencyKey: "create:analysis:lease:cooled" });
  assert.equal(afterCooldown.outcome, "created");
  assert.notEqual(afterCooldown.job.id, created.job.id);
  assert.equal(await store.getOwned("another-user", created.job.id), null);
  sqlite.close();
});

test("a retryable failure on the final attempt releases exactly once", async () => {
  const { sqlite, d1 } = await database();
  addUserAndGrant(sqlite);
  const store = new D1AnalysisStore(d1);
  const created = await store.create({
    userId: "user-analysis",
    matchId: "8963624400",
    playerSlot: 0,
    idempotencyKey: "create:analysis:final-retry",
  });
  assert.equal(created.outcome, "created");
  sqlite.prepare(`
    UPDATE analysis_jobs SET attempt = max_attempts - 1 WHERE id = ?
  `).run(created.job.id);

  const claimed = await store.claimOwned("user-analysis", created.job.id);
  assert.equal(claimed.outcome, "claimed");
  assert.equal(claimed.claim.attempt, claimed.claim.maxAttempts);
  const failure = {
    code: "OPENAI_RATE_LIMITED",
    message: "AI-сервис временно ограничил частоту запросов.",
    retryable: true,
    retryAfterSeconds: 23,
  };
  assert.deepEqual(await store.fail(claimed.claim, failure), { outcome: "failed" });
  assert.deepEqual(await store.fail(claimed.claim, failure), { outcome: "failed" });

  const detail = await store.getOwned("user-analysis", created.job.id);
  assert.equal(detail.job.state, "failed");
  assert.equal(detail.job.failure.retryable, false);
  assert.equal(
    sqlite.prepare(`
      SELECT COUNT(*) AS total
      FROM entitlement_ledger
      WHERE resolution_of = ? AND entry_type = 'release'
    `).get(claimed.claim.reservationId).total,
    1,
  );
  assert.equal(
    sqlite.prepare("SELECT SUM(delta) AS balance FROM entitlement_ledger WHERE user_id = ?")
      .get("user-analysis").balance,
    1,
  );
  sqlite.close();
});

test("retry cooldown is durable and an expired lease can be recovered or canceled", async () => {
  const { sqlite, d1 } = await database();
  addUserAndGrant(sqlite, "user-analysis", 2);
  const store = new D1AnalysisStore(d1);
  const created = await store.create({
    userId: "user-analysis",
    matchId: "8963624400",
    playerSlot: 0,
    idempotencyKey: "create:analysis:cooldown",
  });
  const firstClaim = await store.claimOwned("user-analysis", created.job.id);
  assert.equal(firstClaim.outcome, "claimed");
  assert.deepEqual(await store.fail(firstClaim.claim, {
    code: "OPENAI_RATE_LIMITED",
    message: "AI-сервис временно ограничил частоту запросов.",
    retryable: true,
    retryAfterSeconds: 23,
  }), { outcome: "queued", retryAfterSeconds: 23 });

  const coolingDown = await store.claimOwned("user-analysis", created.job.id);
  assert.equal(coolingDown.outcome, "busy");
  assert.ok(coolingDown.retryAfterSeconds >= 1 && coolingDown.retryAfterSeconds <= 23);
  assert.equal((await store.getOwned("user-analysis", created.job.id)).job.attempt, 1);

  sqlite.prepare(`
    UPDATE analysis_jobs SET retry_not_before = '2000-01-01 00:00:00' WHERE id = ?
  `).run(created.job.id);
  const recovered = await store.claimOwned("user-analysis", created.job.id);
  assert.equal(recovered.outcome, "claimed");
  assert.equal(recovered.claim.attempt, 2);
  assert.equal((await store.cancelOwned("user-analysis", created.job.id)).outcome, "unchanged");

  sqlite.prepare(`
    UPDATE analysis_jobs SET lease_expires_at = '2000-01-01 00:00:00' WHERE id = ?
  `).run(created.job.id);
  const canceled = await store.cancelOwned("user-analysis", created.job.id);
  assert.equal(canceled.outcome, "canceled");
  assert.equal(canceled.detail.job.state, "canceled");

  const artifacts = await buildEvidenceBundle(normalizeOpenDotaMatch(makeOpenDotaMatch()));
  assert.equal(await store.complete(recovered.claim, {
    evidenceBundle: artifacts.evidenceBundle,
    evidenceHash: artifacts.evidenceHash,
    report: makeReport(artifacts.evidenceHash),
    normalizerVersion: "normalized-match.v1.opendota-1",
    model: "model-test",
    promptVersion: "prompt-test",
  }), false);
  assert.equal(
    sqlite.prepare("SELECT SUM(delta) AS balance FROM entitlement_ledger WHERE user_id = ?").get("user-analysis").balance,
    2,
  );
  sqlite.close();
});

test("queued cancellation and an exhausted expired lease cannot strand a credit", async () => {
  const { sqlite, d1 } = await database();
  addUserAndGrant(sqlite, "user-analysis", 2);
  const store = new D1AnalysisStore(d1);
  const canceledJob = await store.create({
    userId: "user-analysis",
    matchId: "8963624400",
    playerSlot: 0,
    idempotencyKey: "create:analysis:cancel",
  });
  assert.equal(canceledJob.outcome, "created");
  const canceled = await store.cancelOwned("user-analysis", canceledJob.job.id);
  assert.equal(canceled.outcome, "canceled");
  assert.equal(canceled.detail.job.state, "canceled");
  assert.equal((await store.cancelOwned("user-analysis", canceledJob.job.id)).outcome, "canceled");

  const exhaustedJob = await store.create({
    userId: "user-analysis",
    matchId: "8963624401",
    playerSlot: 0,
    idempotencyKey: "create:analysis:exhausted",
  });
  assert.equal(exhaustedJob.outcome, "created");
  const claimed = await store.claimOwned("user-analysis", exhaustedJob.job.id);
  assert.equal(claimed.outcome, "claimed");
  sqlite.prepare(`
    UPDATE analysis_jobs
    SET attempt = max_attempts, lease_expires_at = '2000-01-01 00:00:00'
    WHERE id = ?
  `).run(exhaustedJob.job.id);
  assert.equal((await store.claimOwned("user-analysis", exhaustedJob.job.id)).outcome, "terminal");
  const exhaustedDetail = await store.getOwned("user-analysis", exhaustedJob.job.id);
  assert.equal(exhaustedDetail.job.state, "failed");
  assert.equal(exhaustedDetail.job.failure.code, "ANALYSIS_ATTEMPTS_EXHAUSTED");
  assert.equal(exhaustedDetail.job.failure.retryable, false);
  assert.equal(
    sqlite.prepare("SELECT SUM(delta) AS balance FROM entitlement_ledger WHERE user_id = ?").get("user-analysis").balance,
    2,
  );
  sqlite.close();
});

test("completion persists one immutable grounded report and consumes the reservation", async () => {
  const { sqlite, d1 } = await database();
  addUserAndGrant(sqlite);
  const store = new D1AnalysisStore(d1);
  const created = await store.create({
    userId: "user-analysis",
    matchId: "8963624400",
    playerSlot: 0,
    idempotencyKey: "create:analysis:complete",
  });
  assert.equal(created.outcome, "created");
  const claimResult = await store.claimOwned("user-analysis", created.job.id);
  assert.equal(claimResult.outcome, "claimed");

  const artifacts = await buildEvidenceBundle(normalizeOpenDotaMatch(makeOpenDotaMatch()));
  const report = makeReport(artifacts.evidenceHash);
  assert.equal(await store.complete(claimResult.claim, {
    evidenceBundle: artifacts.evidenceBundle,
    evidenceHash: artifacts.evidenceHash,
    report,
    normalizerVersion: "normalized-match.v1.opendota-1",
    model: "model-test",
    promptVersion: "prompt-test",
  }), true);

  const detail = await store.getOwned("user-analysis", created.job.id);
  assert.equal(detail.job.state, "ready");
  assert.equal(detail.report.evidenceHash, artifacts.evidenceHash);
  assert.equal(
    sqlite.prepare("SELECT COUNT(*) AS total FROM entitlement_ledger WHERE entry_type = 'consume'").get().total,
    1,
  );
  assert.equal(
    sqlite.prepare("SELECT SUM(delta) AS balance FROM entitlement_ledger WHERE user_id = ?").get("user-analysis").balance,
    0,
  );
  assert.throws(
    () => sqlite.prepare("UPDATE analysis_reports SET model = 'changed'").run(),
    /analysis report is immutable/,
  );
  sqlite.close();
});

test("history is owner-scoped and cursor pagination is stable", async () => {
  const { sqlite, d1 } = await database();
  addUserAndGrant(sqlite, "user-analysis", 3);
  addUserAndGrant(sqlite, "another-user", 1);
  const store = new D1AnalysisStore(d1);
  for (const [index, matchId] of ["8963624400", "8963624401", "8963624402"].entries()) {
    const created = await store.create({
      userId: "user-analysis",
      matchId,
      playerSlot: 0,
      idempotencyKey: `create:history:${index}`,
    });
    assert.equal(created.outcome, "created");
    await store.cancelOwned("user-analysis",created.job.id);
  }
  await store.create({
    userId: "another-user",
    matchId: "8963624403",
    playerSlot: 0,
    idempotencyKey: "create:history:other",
  });

  const first = await store.listOwned("user-analysis", { limit: 2 });
  assert.equal(first.jobs.length, 2);
  assert.ok(first.nextCursor);
  const cursor = decodeAnalysisCursor(first.nextCursor);
  assert.ok(cursor);
  const second = await store.listOwned("user-analysis", { limit: 2, cursor });
  assert.equal(second.jobs.length, 1);
  assert.equal(second.nextCursor, null);
  assert.equal(new Set([...first.jobs, ...second.jobs].map((job) => job.id)).size, 3);
  sqlite.close();
});

test("the last daily attempt allowance is atomic and does not mint returned credits", async () => {
  const {sqlite,d1}=await database();try {
    addUserAndGrant(sqlite,"user-analysis",3);const store=new D1AnalysisStore(d1);
    const left=await store.create({userId:"user-analysis",matchId:"8963624400",playerSlot:0,idempotencyKey:"daily:left"});
    const right=await store.create({userId:"user-analysis",matchId:"8963624401",playerSlot:0,idempotencyKey:"daily:right"});
    for(let i=0;i<8;i++)sqlite.prepare("INSERT INTO analysis_attempts(lease_token,job_id,user_id) VALUES (?,?,'user-analysis')").run(`old-${i}`,left.job.id);
    const claims=await Promise.all([store.claimOwned("user-analysis",left.job.id),store.claimOwned("user-analysis",right.job.id)]);
    assert.equal(claims.filter(c=>c.outcome==="claimed").length,1);
    assert.equal(sqlite.prepare("SELECT COUNT(*) AS n FROM analysis_attempts WHERE user_id='user-analysis'").get().n,9);
    const claimed=claims.find(c=>c.outcome==="claimed");await store.fail(claimed.claim,{code:"OPENAI_INVALID_RESPONSE",message:"Invalid response",retryable:false});
    assert.equal(sqlite.prepare("SELECT COUNT(*) AS n FROM analysis_attempts WHERE user_id='user-analysis'").get().n,9);
    assert.equal(sqlite.prepare("SELECT SUM(delta) AS n FROM entitlement_ledger WHERE user_id='user-analysis'").get().n,2);
  }finally{sqlite.close();}
});

test("an abandoned queued job returns its original bucket during history reconciliation", async () => {
  const {sqlite,d1}=await database();try {
    addUserAndGrant(sqlite);const store=new D1AnalysisStore(d1);
    const job=await store.create({userId:"user-analysis",matchId:"8963624400",playerSlot:0,idempotencyKey:"abandoned:one"});
    sqlite.prepare("UPDATE analysis_jobs SET updated_at=datetime('now','-2 days') WHERE id=?").run(job.job.id);
    await store.listOwned("user-analysis");await store.listOwned("user-analysis");
    assert.equal((await store.getOwned("user-analysis",job.job.id)).job.state,"canceled");
    assert.equal(sqlite.prepare("SELECT SUM(delta) AS n FROM entitlement_ledger WHERE user_id='user-analysis'").get().n,1);
    assert.equal(sqlite.prepare("SELECT COUNT(*) AS n FROM entitlement_ledger WHERE entry_type='release'").get().n,1);
  }finally{sqlite.close();}
});
