# Release runbook

This repository builds a Cloudflare Worker package for the Sites control plane.
The CI workflow verifies source and package contracts, but it never deploys,
changes production configuration, or applies a D1 migration.

## Release invariants

- Use Node.js `22.13.1`, matching CI, and install from `package-lock.json`.
- Deploy through the Sites control plane associated with
  `.openai/hosting.json`; do not run `wrangler deploy` against
  `dist/server/wrangler.json`.
- The all-zero D1 ID in generated Worker metadata is a Sites substitution
  marker, not a usable database ID. It is accepted only inside the packaged
  artifact when the binding matches `.openai/hosting.json`.
- Never add that placeholder to a root `wrangler.json`, `wrangler.jsonc`, or
  `wrangler.toml`. `wrangler.types.jsonc` is runtime type generation only and
  intentionally has no entrypoint, account, route, or binding configuration.
- Production deployment and production migrations require separate, explicit
  human approval. CI has neither credentials nor a deploy step.

## Required evidence

From a clean checkout of the candidate commit:

```bash
npm ci
npm run check
npm run audit:advisory
git rev-parse HEAD
sha256sum package-lock.json
```

`npm run check` runs lint, generated Worker typecheck, all unit tests, the
bounded Vinext build, package validation, and the two build-dependent test
files. An unavailable registry, malformed response, audit tool failure, or any
high/critical advisory is a hard failure. A temporary exception requires a
narrow, expiring, reviewed code change plus an owner; CI does not silently
convert a known high/critical finding into a successful release.

Keep the CI URL, commit SHA, lockfile hash, package-verifier output, and audit
triage with the release record. Do not reuse evidence from an older commit.

## Staging procedure

1. Confirm CI passes on the exact candidate SHA and `git status --short` is
   empty after a clean build.
2. Confirm staging uses a non-production Sites project and D1 database.
3. Back up the staging database through the approved control-plane procedure.
4. Review every SQL file in `drizzle/` and the journal. Apply pending migrations
   manually to staging through the control plane; do not invent a Wrangler
   command from the generated placeholder config.
   Before `0005_block_unsettled_coach_orders.sql`, require this query to return
   no rows; investigate rather than deleting or rewriting financial records:

   ```sql
   SELECT user_id, COUNT(*) AS unresolved_orders
   FROM orders
   WHERE user_id IS NOT NULL
     AND product_code = 'coach_30_days'
     AND (
       status IN ('created', 'pending', 'waiting_for_capture')
       OR (
         status = 'succeeded'
         AND (credited_at IS NULL OR fulfillment_status <> 'granted')
       )
     )
   GROUP BY user_id
   HAVING COUNT(*) > 1;
   ```

   The migration creates the stricter unique index before dropping the old one,
   so an existing duplicate fails closed.

   Before `0006_brainy_falcon.sql`, require this query to return no rows. A row
   means semantically duplicate provider transitions were recorded with
   different payload bytes; preserve them for investigation and use a separately
   reviewed forward repair instead of deleting financial evidence ad hoc:

   ```sql
   SELECT provider, event_type, provider_payment_id, COUNT(*) AS deliveries
   FROM provider_events
   GROUP BY provider, event_type, provider_payment_id
   HAVING COUNT(*) > 1;
   ```

   Before `0007_special_ben_grimm.sql`, verify the old full identity index is
   present and that active identities are unique:

   ```sql
   SELECT user_id, match_id, player_slot, report_version, COUNT(*) AS active_jobs
   FROM analysis_jobs
   WHERE state IN ('queued', 'running', 'ready')
   GROUP BY user_id, match_id, player_slot, report_version
   HAVING COUNT(*) > 1;
   ```

   The query must return no rows. Migration `0007` adds the nullable durable
   retry deadline, creates the active-state unique index, and only then drops
   the older full index. This permits a fresh job after `failed` or `canceled`
   without allowing two active reports for one identity.
5. Verify the expected tables and indexes before deploying the Worker package.
6. Deploy the candidate package through the Sites staging workflow.
7. Run smoke checks against the real staging URL:
   - `/`, `/account`, and one read-only API request return expected statuses;
   - an unauthenticated request and a client-supplied `oai-authenticated-*`
     header do not create an authenticated session;
   - the expected D1 binding is available;
   - with Scan still disabled, arbitrary Match IDs are not presented as analysed;
   - in an isolated Scan-enabled pass, valid requests return exactly ten
     privacy-projected roster entries and one factual preview, while a forged
     origin, missing edge IP, oversized/invalid JSON, and the thirteenth request
     in one fixed window fail with the documented status and `Retry-After`;
   - Scan creates no entitlement, order, report, question, or OpenAI request;
     `source_matches.normalized_payload` contains no account ID, player name or
     chat, and `rate_limit_buckets.key_hash` contains no raw IP;
   - expired anonymous rate-limit buckets are deleted by the reviewed retention
     procedure before Scan is promoted beyond the closed beta;
   - the map has the intended imported asset or the documented fallback;
   - image optimization is tested only if the real environment provides the
     `IMAGES` binding;
   - `Strict-Transport-Security`, `X-Content-Type-Options`, `Referrer-Policy`,
     `Permissions-Policy`, and `Content-Security-Policy-Report-Only` are present.
8. Inspect the browser console for CSP reports on navigation, hydration,
   ChatGPT sign-in/out, account pages, and Steam CDN hero images. CSP remains
   report-only until those flows pass. Do not add enforcing frame or opener
   isolation without proving that host embedding and authentication still work.
9. Keep `SCAN_RUNTIME_ENABLED`, `ANALYSIS_RUNTIME_ENABLED`,
   `ANALYSIS_FULFILLMENT_ENABLED`, `PAYMENTS_ENABLED`, and
   `PAYMENT_SETTLEMENT_ENABLED` false unless each separately reviewed path has
   passed its staging matrix. Settlement may be enabled independently only to
   finish orders already created in the same environment and payment mode.
   Before enabling Scan, verify a unique server-only `SCAN_RATE_LIMIT_SECRET`
   (32+ characters), the atomic D1 counter under concurrency, and a scheduled
   cleanup that removes expired `rate_limit_buckets`.
   Possession of an OpenAI key alone is not approval to enable fulfillment: the
   deployed D1 lease/cooldown/recovery matrix and provider timeout behavior must
   pass first.
10. Confirm `APP_ENVIRONMENT`, canonical HTTPS `APP_ORIGIN`, and explicit
    `PAYMENT_MODE` match the staging database. Test mode must have only
    `YOOKASSA_TEST_SHOP_ID` / `YOOKASSA_TEST_SECRET_KEY`; live mode must use the
    separate `YOOKASSA_LIVE_SHOP_ID` / `YOOKASSA_LIVE_SECRET_KEY` pair. Never
    copy orders, credentials, or provider events between those databases.

### Settlement recovery remains a payment go-live blocker

The Worker has no protected operator identity, scheduled reconciliation runner,
coach-question fulfillment, or queue in this milestone. Checkout also has a
source-level paid-catalog capability lock; a deployment flag cannot bypass it.
Do not add a public "replay payment" route: possession
of an order or payment ID is not operator authorization. Until that infrastructure
exists and is exercised in test mode, both payment flags remain off.

During an approved test-mode reconciliation, first capture this bounded candidate
set and compare every row with the authoritative provider API using the matching
environment credentials. Never infer payment success from this query alone:

```sql
SELECT id, user_id, status, fulfillment_status, yookassa_payment_id, updated_at
FROM orders
WHERE environment = :environment
  AND payment_mode = :payment_mode
  AND yookassa_payment_id IS NOT NULL
  AND (
    status IN ('created', 'pending', 'waiting_for_capture')
    OR (status = 'succeeded' AND (
      credited_at IS NULL OR fulfillment_status <> 'granted'
    ))
  )
ORDER BY updated_at
LIMIT 100;
```

An integrity-hash mismatch, unknown legacy environment, inactive owner, provider
identity mismatch, or conflicting ledger grant goes to `manual_review`. It must
not be auto-credited. A production reconciliation implementation additionally
needs protected operator authentication, bounded pagination, an audit record,
single-order idempotency, retry/alert policy, and Workerd/D1 concurrency tests.

Orders created before `0006_brainy_falcon.sql` use the earlier partial request
hash even when their environment is otherwise known. The migration deliberately
does not rewrite that financial evidence: settlement fails closed into
`manual_review`, and an operator must compare the frozen snapshot with the
authoritative provider payment before any separately reviewed repair.

Any failed smoke check blocks promotion. Record the failure instead of
overriding `verify:package` or removing a security header.

## Production promotion

1. Obtain the release approval and a fresh production D1 backup.
2. Reconfirm the candidate SHA and staging evidence.
3. Schedule any D1 migration as an explicit protected operation. CI must not
   apply it automatically. Verify forward compatibility before changing data.
4. Promote the already-verified artifact through the Sites control plane.
5. Repeat the staging smoke matrix on the production URL without creating a
   payment or mutating user data.
6. Monitor Worker errors, authentication failures, D1 errors, and CSP reports.

## Backout

- Stop traffic promotion and disable payment/fulfillment flags first if the
  failed release can accept orders without delivering analysis.
- Roll the Worker back to the last verified artifact through the Sites control
  plane.
- D1 migrations are not rolled back automatically. Restore the reviewed backup
  or apply a separately reviewed forward repair; never run an unreviewed down
  migration during an incident.
- Repeat the read-only production smoke checks and attach the incident/recovery
  evidence to the release record.

## Current limits of automation

CI proves a deterministic source/package contract on Linux. It does not prove
edge TLS policy, control-plane header injection, authentication-header stripping,
the presence of an `IMAGES` binding, production D1 readiness, or browser
compatibility. Those remain staging gates until dedicated integration
environments and protected post-deploy workflows exist.
