# Workshop recovery checkpoint — 2026-09-09

NOT READY FOR DEPLOYMENT. This branch is an emergency source checkpoint, not a release.

The workspace disconnected with `409 environment_offline` during the full public Steam guide import. The module and tests were reconstructed from this agent's completed tool inputs. They have not been compared byte-for-byte with the disconnected working directory. The last local focused test receipt was 11 passed. Full CI, public UI integration and production source readiness have not completed.

Saved scope: bounded public Steam metadata retrieval, KeyValues parsing (including trailing NUL and UTF-16), factual item stages with attribution, explicit positions, conservative slot projection, dated cache, withdrawal tombstones and source freshness states. No guide prose, user account information, provider keys or win rates are included.

Missing: completed `data/workshop_builds.json`, verified 127-hero coverage, complete canonical item recipe compatibility, actual production-transport source readiness, integration with the public router and the builds UI, full required deployment gates. Do not enable an empty catalog or report that all heroes have current-meta builds.

A metadata pass for 359 known public IDs succeeded before the first import exposed the trailing-NUL parser issue. The subsequent fixed import had not produced a confirmed completion before the environment disconnected. Its result must not be inferred. Existing live deployment was not changed by this checkpoint.

Verified source path: Valve documents the credential-free POST `ISteamRemoteStorage/GetPublishedFileDetails/v1/`. Public item metadata returns a public Steam CDN .build URL; the file contains Hero, Title, Role, GameplayVersion and ItemBuild.Items. Only item identifiers and stage ordering are extracted. Private/deleted/banned records are excluded. Metadata refresh never advances the author's update date.

Examples independently observed: ImmortalFaith Viper guide 2975666972 declared 7.41d, public visibility; Torte de Lini Kez guide 3362336316 declared 7.41e and was updated 2026-08-10. Torte's author profile is now private; no private-profile enumeration or access-control bypass is permitted. Known public guide IDs can be checked through the ordinary public metadata API.

Resume with the intended public import, inspect exact coverage and dates, run source readiness and all focused/integration tests, then prepare a distinct reviewed release commit. No production branch is updated here.
