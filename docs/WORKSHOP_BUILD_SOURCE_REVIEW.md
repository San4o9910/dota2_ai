# Public Workshop guides: source recovery and verification

Source verification completed on 2026-09-09. This source branch is not a production deployment.

## Verified coverage

The public Valve hero catalog returned 127 heroes. The recovered dataset contains 369 public, attributed guides covering all 127 heroes. Of these, 172 guides declare Valve's current patch 7.41e and cover all 127 heroes. There are no unknown item identifiers in this imported dataset.

A matching patch declaration is not proof of popularity, win rate or continuing metagame relevance. The application separately marks guides older than 30 days as requiring review, even while the author's declared patch matches. At this receipt, 8 matching-patch guides for 6 heroes were within that review window; the remaining 164 matching-patch guides retained their older author dates and review-due status.

## Evidence

[Source CI 34402881351](https://github.com/San4o9910/dota2_ai/actions/runs/34402881351), job 102638776654, succeeded.

- Focused tests: 14 passed, plus 10 subtests.
- Actual production transport: one public Steam metadata request and one public CDN .build download parsed successfully, with six projected slots and patch 7.41e.
- Snapshot SHA-256, excluding the final newline: f342d52a4840a2a55ab59ae792e08b1dd39630c3df94bfd2ff70f6aab9073f38.
- Independent slot projections reconstructed during workspace recovery matched Python's subsequently executed projections for every guide.
- One candidate, 2958853356, failed source parsing and was excluded. It did not create a hero coverage gap.

No deployment, server provisioning, model calls, provider keys or subscription actions occurred in this source CI.

## Extraction and refresh contract

[Valve's documented GetPublishedFileDetails method](https://partner.steamgames.com/doc/webapi/ISteamRemoteStorage#GetPublishedFileDetails) returns public guide metadata without a key. Only approved public creator IDs, Dota app570, public visibility and non-banned records may supply a CDN file. The parser retains item identifiers and stage ordering, hero/position declarations, author attribution, declared patch and author update date. It does not copy guide prose, tooltips, sponsorship text or statistics.

The known-ID bootstrap is based on previously public guide lists. ImmortalFaith's public collection and a normal global public Hero Build search for Largo supplied newer public guide IDs. Torte's now-private profile was not enumerated. Each candidate was separately validated through the ordinary public metadata API before downloading its guide.

Runtime refresh is bounded to once per day for the reviewed list of public guide IDs. Unchanged metadata does not redownload the guide; changing the feed check time never changes the author's review date. Private, removed or banned guides are withdrawn with persisted tombstones. Access denial stops further attempts until restart. Transient failures retain last known facts with stale status. Unknown item identifiers retain evidence and suppress a complete-current-plan claim. Both NARMA_WORKSHOP_REFRESH_ENABLED=0 and NARMA_EXPLORE_REFRESH_ENABLED=0 disable background refresh for offline tests.

Purchase stages preserve intermediate components. Narma's six-slot illustration removes basic components, consumed upgrades and known component/upgrade duplication, and leaves unfilled slots empty rather than inventing purchases. This illustration is not an observed six-item combination or a measured win-rate ranking.

## Remaining release work

The parent change must integrate the public router/lifecycle and frontend, run its required native PostgreSQL and browser gates, deploy to the existing server and verify the live site. Successful source verification alone does not establish that those steps have happened.
