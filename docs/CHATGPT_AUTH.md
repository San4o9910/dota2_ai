# Personal ChatGPT authorization in Narma

The owner connects an existing ChatGPT account from **Аккаунт → ChatGPT**.
Narma displays a short-lived device code and opens the fixed OpenAI verification
page. The password and confirmation stay on OpenAI. The owner returns to Narma,
which checks the pending login and shows the actual connection state.

This uses the ChatGPT/Codex subscription authorization flow documented by
[OpenAI](https://learn.chatgpt.com/docs/auth), following the native adapter in
[the pinned Hermes source](https://github.com/NousResearch/hermes-agent/blob/9fd44b4dfc44138b9e5d5689acb56c438364ff7b/hermes_cli/auth_codex.py).
It does not create an OpenAI API key. Availability, model access and usage depend
on the owner's subscription and account settings. Device authorization may need
to be enabled in the account's security settings.

## Runtime responsibilities

- Gemini retains its existing video analysis path and historical dollar ledger.
- The replay coach sends selected-player facts, hero, confirmed position and the
  current training exercise to ChatGPT, then validates the response against the
  actual evidence IDs. It does not claim to have watched video frames.
- The actual pinned Hermes AIAgent runs on the existing server in an isolated
  worker and tracks patterns across ready matches. Its one model request goes
  through Narma's private broker to the owner's ChatGPT connection.
- `HERMES_PROVIDER=chatgpt_subscription` and
  `REPLAY_COACH_PROVIDER=chatgpt_subscription` explicitly select this path. Missing
  authorization, exhausted limits or invalid output do not invoke Gemini as a
  fallback. Factual reports remain available.

The initial model is `gpt-5.4`, from the pinned native adapter's model allowlist.
An account that cannot use it receives a bounded unavailable/reconnect state;
the service does not silently switch provider or account. This integration uses
the native Codex Responses transport, not an exposed Codex app server, shell or
shared public ChatGPT proxy. It is scoped to this pilot's sole owner. A future
multi-customer product needs its own supported account and provider design.

## Authorization and durable attempts

`GET /api/integrations/chatgpt` returns a safe connection snapshot.
`POST /connect` starts explicit authorization, `POST /poll` checks the supplied
authorization generation, and `DELETE /api/integrations/chatgpt` disconnects it.
All routes require the existing owner session; mutations also require the
existing same-origin CSRF checks. Pending codes and responses use `no-store`.

Pending credentials, access and refresh tokens are authenticated-encrypted in
PostgreSQL. The server generates and preserves `NARMA_CHATGPT_ENCRYPTION_KEY`;
it is not sent to the browser or Hermes worker. Token refresh is serialized.
Disconnect clears the encrypted credentials and replaces the generation, so a
late poll or old task cannot restore the connection. Unknown one-time token
exchange or refresh outcomes require a fresh explicit login.

The subscription ledger `chatgpt_calls` pins the owner, source, lease, request
digest and authorization generation before dispatch. Each job/task permits one
attempt. Completed text is stored only after a valid terminal stream; truncated,
unknown or already attempted requests are not automatically resent. Reconnecting
does not erase attempt history. Explicit login enables the first ChatGPT review
of eligible facts that previously failed on Gemini; the old Gemini records and
reservations remain untouched. Successfully reviewed facts are deduplicated.

Usage is labeled `chatgpt_subscription`; API cost is unknown/not applicable and
is never recorded as a zero-dollar Gemini call. The deployment defaults to six
combined replay/Hermes requests per UTC day. A provider quota response pauses new
requests; only a provider-supplied reset is used as a reset time. Text size,
response size, transport time and runner time are bounded. No tools or automatic
provider retries are enabled.

## Deployment and acceptance

The deployment's `--prepare-chatgpt-auth` path installs the connection routes and
starts Hermes waiting for the owner's login. It verifies migrations, access
controls, the pinned runtime, private networking, and unchanged historical
Gemini accounting without making a generation request. It preserves the
encryption key and prior worker settings through rollback.

The preparation gate proves that the services are ready for authorization.
`connected` proves only that authorization succeeded. Hermes is runtime-verified
only after a real, source-valid review and its successful subscription ledger
record. No browser fixture or deployment smoke is treated as such a review.

Offline tests cover owner/CSRF gates, encrypted credentials, login expiry,
refresh/disconnect races, lease and source fences, quota handling, malformed SSE,
one-attempt accounting and the mobile/desktop login UI. Native PostgreSQL and
the real pinned Hermes smoke remain mandatory deployment gates.
