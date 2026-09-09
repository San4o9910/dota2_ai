# STRATZ rollout status — 2026-09-09

## Independently authorized authored release

The owner subsequently approved progress with authored guides and alternative
sources. That release selects `NARMA_BUILD_STATS_SOURCE=authored`, adds 12
conditional six-slot variants and official patch review notes, and does not
activate STRATZ. A stored token never activates the provider. Standalone source
diagnostics now require manual dispatch; enabled STRATZ deployment still requires
the real source-data gate below. The source blocker itself is unresolved.
See `BUILD_SOURCE_REVIEW.md` for the distinct authored-content scope.

The deployment receipts below describe the prior blocked STRATZ candidate,
not a claim that a later authored release has failed or enabled statistics.

**Blocked; not deployed.** The working site retains release
`c9632736dc0f18ce57b662490401e8edb6c074b4` with 12 authored six-slot guides.
The integration candidate is `fdac732328ec50d7ad3526bfd124743ab304ce82` on
`codex/replay-map-hardening-8ea829a`. This follow-up branch records the blocker
and makes the pending refresher stop after authentication/access denial.

## Confirmed

- The owner added `STRATZ_API_TOKEN` as a GitHub Actions secret.
- Authorized schema inspection succeeded: run `34337740213`.
- Public Viper/mid/Herald–Guardian purchase data were received. The full
  minute range/threshold check returned 3018 rows for source week 2957.
- The official API documentation requires `User-Agent: STRATZ_API`; both
  transports now send it. Source: <https://stratz.com/api>.
- One production-client call reached data validation and returned
  `cohort_mismatch`. The exact returned rank/position markers remain unverified;
  do not weaken cohort validation without observing and explaining them.
- Subsequent attempts with the documented header returned HTTP 403, including
  the exact production adapter. No redirects, proxy changes, credential
  extraction or access-denial retries were used to force access.

## Latest blocking receipts

- Source verification run `34342075268`, job `102434940541`:
  `stratz_adapter_check_failed / access_denied`.
- Timeweb deployment run `34342075262`, job `102434940240`:
  `stratz_adapter_check_failed / access_denied`. The deployment step was skipped.
  No STRATZ credential was installed on the VPS and no new release was activated.

The denial's cause is not established: do not claim an invalid key, a specific
quota, an IP block, or a provider outage as proven. The next external step is to
verify access for this token/application with STRATZ. Never request the token in
chat. No further upstream diagnostic attempts are queued by this handoff.

## Prepared implementation and validation

Prepared code includes the public stats endpoint, hourly bounded refresh,
persistent dated cache, real rank brackets, individual item win rates/counts/
purchase-minute averages, and compatible six-slot suggestions drawn from the
authored hero/role pool. It does not provide a measured joint-build win rate or
guarantee an exact per-match patch: see `STRATZ_SETUP.md` for these limitations.

Local: 8 purchase/selection tests, 64 ops tests, and the public mobile/desktop
regression suite passed. CI public/private UI gates and image imports passed.
A separate offline workflow `34342762182` passed **19** purchase/selection,
API/cache/transport and permission-stop tests, plus **64** ops tests. It used no
provider credentials or calls. The full native PostgreSQL/API deployment suite
has not completed for this candidate because the actual source gate stopped
the release before that stage. The live STRATZ integration remains unverified.

## Resume after provider access is resolved

1. Run the exact adapter verification with the existing protected secret.
2. If it reaches `cohort_mismatch`, inspect only validated rank/position markers
   from the receipt and confirm the filter/aggregation semantics before editing
   the normalizer. Keep rejection of genuinely mismatched cohorts.
3. Run the API/cache tests and all existing deployment gates. Do not skip the
   actual source-data gate to publish a "working" integration.
4. Merge the permission-stop follow-up only after validation, deploy through
   the existing Timeweb workflow, then inspect live rank/mode switching and the
   single selected item card. Confirm no secret appears in public output.

No AI generation, budget increase, new server or changes to account identity
were authorized or performed by this statistics integration.
