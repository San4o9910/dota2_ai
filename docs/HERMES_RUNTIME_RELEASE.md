# Hermes runtime release — 2026-09-08

## Verified before publication

- Official unmodified AIAgent source pinned to
  `9fd44b4dfc44138b9e5d5689acb56c438364ff7b`; 63 dependencies installed from its
  upstream lockfile. Actual runtime smoke: valid JSON, malformed JSON, provider
  error without retry, hard process deadline and recovery after failure all pass.
  Exactly one provider request per case, no auxiliary request, disposable
  profiles removed. Measured peak child RSS: about 127 MiB.
- Local isolated PostgreSQL-compatible service suite: 309 passed, one optional
  native replay test skipped. Native PostgreSQL is an additional CI gate.
- Follow-up lease checks: all 14 task tests pass; the additional actual budget-row
  contention test requires native PostgreSQL and runs in CI. The full captured
  AIAgent request passes the real broker request validator unchanged.
- Deployment regression suite: 25 passed. Browser regressions are prepared for
  390 and 1440 pixels, including recommendation filtering and event navigation;
  actual Chromium runs in CI.
- Existing applied migrations are unchanged. Migration 011 adds durable runtime
  tasks and explicit Hermes provider-call attribution. No budget reset, new
  provider credential, server or additional allowance is included.

## Production activation

Not yet confirmed. The release pipeline must still build and verify the actual
Docker runtime and network isolation, run native PostgreSQL and Chromium gates,
then inspect server resources and complete one bounded live review through the
shared provider ledger. Record the exact deployed source revision, workflow and
before/after accounting here after that activation succeeds.
