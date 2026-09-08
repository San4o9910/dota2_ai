# Curriculum release: deploy the product without starting Hermes

Historical release note: the subsequent owner-authorized ChatGPT release uses
the explicit preparation path described in [CHATGPT_AUTH_RELEASE.md](CHATGPT_AUTH_RELEASE.md).
The disabled-runtime behavior below remains available through plain `pilot.py`;
it is no longer the current production workflow's push mode.

The ordinary `timeweb-pilot.yml` push deploy and `python3 ops/timeweb/pilot.py`
preserve an already stopped Hermes runtime. They deploy the API, curriculum,
portal and replay worker. They do not schedule a Hermes review or modify the
provider allowance. A stopped runner is never reported as connected.

The deployment checks the previous worker snapshot before stopping services.
If either Hermes service was running, the default mode fails before bootstrap;
it cannot silently disable an active integration. For the existing stopped
runtime, it verifies both services remain stopped after activation, the Hermes
provider-call count is unchanged, the owner identity is unchanged and the
protected budget fields and uncertain reservations are preserved.

## Separate explicit activation

`workflow_dispatch` has `activate_hermes: false` by default. Setting it to true
maps to `pilot.py --activate-hermes`. This remains the existing activation path:
available-resource and allowance checks, isolated runner network, one accounted
review or reuse of an identical verified review, settled usage, pinned runtime
revision and fresh scheduler heartbeat. The switch grants no new budget and
does not reconcile, refund or retry an uncertain charge.

Do not select activation for the curriculum update. The known pre-release
allowance had 275,062 micro-USD available, below the 1,200,000 micro-USD
reservation for a review. This is a recorded earlier observation, not a new
balance lookup. Deployment logs contain the freshly read balance.

## Release checks

1. Existing HTTPS, source-image, database readiness, anonymous access, CSRF and
   replay runtime gates remain in place. `/api/learning` must return HTTP 401
   anonymously; the public `/hero-pool` shell remains accessible.
2. Migration `012_learning_curriculum.sql` and the `learning_plans` and
   `learning_checks` tables must be present.
3. With all analysis and Hermes workers stopped, the real learning read
   functions run against existing owners with PostgreSQL
   `default_transaction_read_only=on`. The check creates no accounts, sessions,
   plans, answers or provider calls. Every history row is checked against that
   owner's current player binding and uploads; up to three reports per owner
   are checked for hero, manual position, replay digest and exact event/time
   references. All six catalog role variants are checked.
4. The provider-call count must stay unchanged throughout that learning check.
   Logs contain only aggregate counts. A zero-report result makes no claim of
   validating live replay evidence. Existing customer requests after worker
   restart are separate from the deployment check.
5. A failed learning, replay or Hermes activation gate restores the previous
   runtime images/API and previous running workers. Additive learning tables
   and existing financial records are retained; this is not a database rollback.

The release enables the curriculum and practice workflow using replay evidence
and explicit player reflections. It does not establish a Gemini-to-OpenAI
analysis chain, provide OpenAI credentials, prove coach-model quality or activate
the stopped Hermes integration. Those capabilities must not be presented to
customers as working because the product deployment passes.

Local verification:

```bash
python3 -m unittest discover -s ops/timeweb/tests -p 'test_*.py' -v
python3 -m compileall -q ops/timeweb
```

Actual live deployment evidence belongs in the release record after the workflow
finishes. This document itself is not a claim that the release has been deployed.
