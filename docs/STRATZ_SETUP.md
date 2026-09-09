# STRATZ schema inspection

The build catalog does not yet have an authorized STRATZ statistics adapter. The
operator can add a GitHub Actions repository secret named `STRATZ_API_TOKEN`,
using a token obtained for this application at <https://stratz.com/api> under
STRATZ's applicable access and commercial-use terms. Do not put the token in a
commit, command argument, issue, browser code, or workflow output.

The existing **Timeweb pilot deployment** workflow runs
`python3 ops/timeweb/check_stratz.py` before server provisioning. The token is
available only to that inspection step; it is not copied to the Timeweb server.

The separate **STRATZ source verification** workflow runs a targeted inspection
of build-related schema types through `scripts/inspect-stratz-builds.py`, with at
most four metadata requests and without deployment, server credentials or AI generation. It requires the secret
to be present and runs when its workflow file changes on the pilot branch, or by
manual dispatch. This isolates provider setup from the live application's rollout.

- No secret: `source_not_configured`, exit 0. This does not block a UI release.
- Authorized introspection: `stratz_schema_inspected`, exit 0. The output contains
  only validated schema names, argument types and enum names; omitted fields and
  types have explicit counts. `popular_builds_ready` remains `false`.
- Authentication, HTTP, transport or schema failure: a fixed error code, exit 1.
  Raw response errors, redirects and credentials are never printed. A configured
  but failing source blocks deployment so the failure cannot look like readiness.

The script sends at most two read-only GraphQL introspection queries to the fixed
`https://api.stratz.com/graphql` endpoint. It reads query fields and the matching
type metadata for matches, players, hero statistics and collections; it does not
invoke those data fields, fetch private matches, or make an AI generation call.
Redirects and environment proxies are disabled. Each response has a 2 MiB limit;
socket and body-read time are bounded. No retries are made.

After a successful inspection, an implementation still needs to verify the real
authorized fields for full six-item combinations, matches/wins, sample size,
patch, date window, position, rank bracket, pagination and refresh behavior. It
must also confirm permitted product use and account quotas. A hero or individual
item win rate must not be presented as the win rate of a complete build. Only
after those checks and a tested adapter should popular/high-win-rate build
collections and automatic statistics refresh be enabled. This inspector alone
does not enable those features or establish a commercial data license.

Reference: [GraphQL introspection](https://graphql.org/learn/introspection/).
