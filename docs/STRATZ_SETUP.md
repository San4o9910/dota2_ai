# STRATZ build statistics

The application uses `STRATZ_API_TOKEN`, stored as a GitHub Actions repository
secret. Obtain it through <https://stratz.com/api>. Never paste credentials into
issues, commits, browser code or logs. Deployment transfers the validated token
over SSH stdin into the existing server's mode-0600 environment file. Database
identity and other provider credentials are preserved.

Every request includes the documented `User-Agent: STRATZ_API` and bearer token.
The production adapter initially returned HTTP 403 with a different client
header; this was diagnosed separately from token validity. Requests are not
retried after access denial. The required header is documented at
<https://stratz.com/api> and covered by an offline transport regression test.

## Verified source and actual scope

Authorized introspection and bounded public data checks succeeded on 2026-09-09.
The verified source is `heroStats.itemFullPurchase`: per-item match/win counts by
purchase minute, hero, position and basic rank bracket. Explicit `minTime:0`,
`maxTime:75`, `matchLimit:1` avoids the default threshold hiding most purchases.
The initial Viper/mid/Herald–Guardian request returned 26 rows; the explicit range
and threshold returned 3018. The API documents an omitted week as its current week.
The returned week index was 2957; the client does not pretend that a fetch timestamp
is the time of the last match included by the provider.

**This endpoint does not supply joint six-item build win rates or popularity.**
Narma never multiplies/averages individual item win rates into a build win rate.
`joint_build_winrate` is null. STRATZ's winning Immortal guides are not used as a
wins-and-losses sample. No private account identities, OpenDota, scraped competitor
pages, or AI generation are used by this feature.

## User experience

The 12 existing hero/position guides retain their authored six-slot plans. The
rank selector exposes the four actual provider brackets, without invented exact
MMR boundaries. Two additional modes select six compatible items from the guide's
reviewed hero/role pool using item purchase frequency or item win-rate evidence.
They are labelled as per-item selections, not the most popular joint build.

- Popularity requires at least 30 recorded matches per item.
- Win-rate selection requires at least 100 and sorts by the 95% Wilson lower bound.
- Recipes, low-cost components, duplicate boot slots and known component/upgrade
  pairs are excluded. Reviewed upgrade relationships also cover missing component
  metadata in STRATZ's current constants response.
- Only instance 0 purchase-minute buckets are combined; repeated instances are
  excluded. Duplicate buckets, mixed weeks, other heroes/roles/ranks and impossible
  win counts fail validation.
- If six evidenced items cannot be selected, the UI explicitly shows the authored
  plan, without fabricated items or statistics. The selected item displays its
  match count, win rate and weighted mean purchase minute.
- The UI explains that expensive late-game items have outcome-selection bias and
  that their win rates do not establish causal benefit.

## Freshness and known limitations

One bounded in-process worker refreshes requested cohorts hourly. The default
12 Herald–Guardian cohorts are warmed automatically. The finite request space is
12 guide/position pairs × 4 brackets. Requests are serialized with a two-second
minimum gap; an error applies a global five-minute backoff. Metadata refreshes
hourly. Responses are limited to 2 MiB with bounded timeouts, no redirects and no
ambient proxies. The public endpoint cannot submit arbitrary GraphQL queries.

Validated public snapshots persist atomically at
`VIDEO_STORAGE_PATH/public/build-statistics.json` on the existing media volume.
Source failures retain dated evidence. Snapshots older than two hours or from a
previous source week cannot produce current suggestions. A new Valve patch
suppresses derived plans for seven days to avoid mixing weekly data across patches;
a changed patch also requires review of the authored candidate pool. Unknown or
stale Valve patch information suppresses suggestions while preserving the guide.

STRATZ's constants response currently ends at 7.40b whereas Valve reports 7.41e.
This is **not** represented as proof that the purchase sample is for 7.40b or
7.41e: the per-item endpoint does not expose a patch ID. Current-week checking and
the conservative patch-transition gate reduce stale-data risk, but do not create
an exact per-match patch guarantee or a global joint-build ranking. Those require
a supported provider dataset with the missing dimensions.

## Checks and operations

`STRATZ source verification` is a separate read-only GitHub workflow for schema and
bounded aggregate diagnostics, without deployment or server credentials.
The Timeweb deployment also runs the schema check and
`python -m narma_video.build_meta --check` in the built image, then verifies the
anonymous live `/api/explore/builds` route after rollout. Offline tests exercise
cohort validation, sample-size selection, compatibility, stale persistence,
patch changes, secret installation and mobile/desktop UI behavior.

Set `NARMA_STRATZ_REFRESH_ENABLED=0` on the API to disable the refresher. The code
requires a configured token to start it. No AI allowance or subscription billing
is changed by this integration.
