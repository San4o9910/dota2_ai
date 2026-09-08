# Owner ChatGPT authorization and Hermes readiness

The production branch now explicitly invokes `pilot.py --prepare-chatgpt-auth`.
It prepares the existing owner's ChatGPT connection and the isolated Hermes
services. The owner completes the OpenAI device authorization from Narma's
account settings. A green deployment means the services can accept that login;
it does not prove a completed model review.

## Deployment sequence

1. Keep the existing pinned Timeweb VM, PostgreSQL volume, owner, player binding
   and Gemini allowance. Build and test the exact source before installation.
2. On the server, `write_secrets.py` generates a Fernet encryption key only when
   none exists and the existing database has no ChatGPT connection. A missing key
   with existing connection rows blocks deployment. A malformed existing key is
   never replaced. The key stays in `/opt/narma/secrets/video.env`, mode `0600`;
   it never enters GitHub secrets, artifacts, application responses or logs.
3. Set `REPLAY_COACH_PROVIDER=chatgpt_subscription` and
   `HERMES_PROVIDER=chatgpt_subscription`. Supply the encryption key only to the
   portal API, replay worker and Hermes broker. The Hermes runner has neither
   database credentials nor OAuth tokens and only joins the internal network.
4. Stop analysis workers and apply migrations 013–015. Run the normal parser,
   owner, hero-pool and curriculum checks. Start the Hermes runner and a broker
   whose scheduler is paused.
5. `prepare_chatgpt_auth.py` checks the actual runner revision, broker health,
   private network and blocked external destinations, including `chatgpt.com`
   and `auth.openai.com`. The actual owner's connection and runtime status are
   read in read-only database transactions. Anonymous connection reads return
   `401`; a connection request with a foreign origin returns `403`.
6. Compare the entire historical Gemini budget/provider ledger fingerprint and
   the subscription-call count before and after readiness checks. There is no
   `process_once`, generation request, budget increase, charge reconciliation or
   synthetic model review in this gate.
7. Enable the scheduler and then the replay worker. With no owner authorization,
   Hermes reports `waiting_auth` and schedules no provider work. After a valid
   owner login it can perform ordinary authorized reviews. `runtime_verified`
   becomes true only after an actual valid review for the current connection.

`NARMA_CHATGPT_MAX_DAILY_CALLS` defaults to six shared subscription attempts per
owner per day. Subscription calls have their own ledger and do not consume or
reconcile the historical Gemini API allowance. They are not reported as zero-cost
OpenAI API calls. Subscription availability still depends on the owner's actual
plan and provider limits.

## Rollback and recovery

Rollback restores the previous API and every previously running analysis/Hermes
service using captured immutable images. It also restores only the prior
provider-selection settings. It never deletes or rotates the encryption key,
changes accounts, removes OAuth rows or rewrites any provider ledger.

Keep the server's encryption key with its private operational credentials during
backup/recovery. PostgreSQL backups contain encrypted connection data; a database
backup alone cannot restore a working connection on a new server without the
matching key. The deployment deliberately refuses to replace a lost key over
existing credentials. Do not put the env file into public repository files,
workflow output or unencrypted diagnostic artifacts.

The workflow retains the older manual Gemini activation input for explicit
legacy operation. It is mutually exclusive with ChatGPT preparation, and all
original paid-review, source and budget gates still apply. A normal push uses
ChatGPT preparation and never invokes that legacy activation.

Local verification for this change includes 40 deployment unit tests, Python
compilation and shell validation. The workflow additionally runs native
PostgreSQL API tests, real Docker network checks and mobile/desktop portal QA.
Live readiness and a completed owner login are separate operational results;
the source documentation makes no claim that either has already happened.
