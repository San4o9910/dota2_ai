# Independent Clarity replay parser

Local parser used by the isolated `replay-worker` service. It imports **Clarity 4.0.1 directly**. No OpenDota API, OpenDota parser, HTTP calls, AI service, transcript, or video decoding takes place while the replay runs.

## Build and run

Java 17+, Python 3, and curl:

```bash
python3 bootstrap.py
python3 run_bounded.py /absolute/replay.dem /absolute/new-private-output-directory
```

The first command fetches SHA-256-pinned JARs from Maven Central; the second runs entirely locally. `pom.xml` is also provided for an ordinary Java 17 / Maven server environment. `bootstrap.py` uses the Eclipse Java compiler because this research environment had a Java runtime without the JDK compiler.

The runner caps Java heap at 2 GiB, wall time at 300 seconds, CPU time at 295 seconds, and each output file at 50 MiB. The parser additionally caps JSONL output at 50 MiB and input at 512 MiB. These process limits are not a substitute for a production container sandbox, read-only filesystem, network isolation, job authorization, or hostile-input fuzz testing.

Output files are `events.jsonl`, `summary.json`, `run.log`, and `run-metrics.json`. A successful exit and final `summary` event establish that this selected-handler pass reached the end. Interrupted/failed output must remain marked incomplete. All replay input and output belongs in private, owner-scoped storage.

## What the probe records

- SHA-256, file metadata, match ID from the epilogue, build/network protocol, playback ticks, and final tick reached. The private source summary includes the match roster for identity verification; never send it to public logs or return it to the browser.
- Separate creation, state change, network scope enter/leave, and explicit deletion observations for placed ward NPCs and actual `CDOTA_BaseNPC_Tower` entities. Ward inventory items and Watch Towers are excluded.
- Entity handle, index **and serial**, raw owner ID/handle, team, health, life state, exact building entity name, raw cell/offset positions, and source creation time when available.
- Combat-log deaths for towers/wards, with their own authoritative combat timestamps. No forced handle match is invented where the combat log lacks a unique entity handle.
- Demo tick, server tick, tick interval, recorded pause fields, start time, and a **derived** game-clock estimate. `matchTime` stays absent when no direct networked game-time property exists. The derived estimate is separately named and needs in-game validation, especially across pauses.

## Lifecycle rules for integration

1. `CDOTA_NPC_Observer_Ward` and `CDOTA_NPC_Observer_Ward_TrueSight` are placed NPCs. `CDOTA_Item_ObserverWard` and `CDOTA_Item_SentryWard` are inventory items and must not become map ward markers.
2. Hide a ward when its confirmed life state first becomes dying/dead. **Do not wait for entity deletion**: it can occur several seconds after the ward stopped granting vision. Keep expiration versus attack destruction unknown until independently supported. `scope_left` is never a ward death or team-visibility fact.
3. Resolve `m_pEntity.m_nameStringTableIndex` through `EntityNames` for tower identities. `m_iUnitNameIndex` uses a different indexing domain and must not be used with that table. The exact `tower4_top` and `tower4_bot` names keep both base towers separate.
4. Preserve raw cell/offset coordinates until a patch-specific map transform is validated. Do not infer world coordinates or minimap alignment from this probe alone.
5. Do not use metadata roster order or raw player owner IDs as canonical player slots. The report builder resolves Steam identity through PlayerResource and team resources, rather than roster position. This does not implement client fog-of-war or pixel rendering.

## Real-file verification (2026-09-06)

An owner-provided 169,982,117-byte Source 2 replay was parsed locally through final tick **152653**, with 152654 tick callbacks, 76312 non-synthetic ticks, and build **10836**. Selected event handlers found:

- **81 placed ward NPCs**: 49 Observer and 32 TrueSight. All 81 have explicit life-state transitions and subsequent deletion.
- **22 actual towers**, including separately identified T1/T2/T3 and both T4s per team. Eighteen have life-state transitions and subsequent deletion.
- **99 ward/tower combat-log deaths** and 2261 tower state changes.

In the validated run, elapsed wall time was **5.84 seconds** and peak resident memory **799008 KiB**. This is one-file prototype timing, not a capacity benchmark or production guarantee. All 81 ward deletions lagged the first dying/dead observation by **5.8–10.07 seconds**, demonstrating why deletion must not define the end of ward vision.

Across the 99 combat deaths, the server-tick-derived clock differed from the combat timestamp by between approximately **-0.000082 and +0.033561 seconds**. This replay reported no paused ticks; pause correction remains unvalidated. No matching Dota-client/video validation has been performed. These timings describe the original ward/tower handler set; the current full report extracts combat and player resource snapshots as well.

Raw output remains outside Git. Only these reusable sources and dependency lock should be integrated into the project.

## Primary references

- [Clarity and Maven coordinates](https://github.com/skadistats/clarity)
- [Clarity examples and lifecycle callbacks](https://github.com/skadistats/clarity-examples)
- [Clarity 4.0.1 POM](https://repo.maven.apache.org/maven2/com/skadistats/clarity/4.0.1/clarity-4.0.1.pom)
- [Clarity protobuf 6.1 POM](https://repo.maven.apache.org/maven2/com/skadistats/clarity-protobuf/6.1/clarity-protobuf-6.1.pom)

Dependency coordinates, download URLs, versions, and SHA-256 hashes are pinned in `dependencies.lock.json`. Clarity is BSD-licensed; retain dependency licenses when distributing artifacts.

## Standalone match-analysis integration (2026-09-07)

The portal now submits `.dem` files to `/api/replays`, with immutable chunk uploads, owner-scoped storage and nickname-to-Steam binding from the replay metadata. The separate Python `narma_video.replay_worker` runs this Java parser through EOF, validates the source hash and selected identity, and stores a personal report in PostgreSQL. The browser receives only the selected player report.

Combat events include deaths, kills, assists, reincarnation, purchases, buybacks and item/ability usage. Resource snapshots provide final K/D/A, farming, economy and damage. The final resource snapshot is emitted at EOF so late events are not lost between sample intervals. Event timestamps come from combat time relative to recorded game start; economy uses the separately derived server clock.

### Item and income evidence

`hero_inventory` records changed item lists after each complete network tick, with the hero's full handle, item handles, resolved `EntityNames`, slot, raw purchase/assembly timestamps, and purchaser ID. `selectedPlayerIndex` is resolved by matching `m_vecPlayerTeamData.*.m_hSelectedHero` to the full hero handle. The hero's raw `playerId` is retained separately and must not be substituted for that index. Replicating hero entities and explicit illusions are excluded. An unresolved item name is marked incomplete and retried; it is never evidence that an item vanished.

Slots 0–5 are active inventory, 6–8 backpack, 9–14 stash, 15 Town Portal Scroll, and 16 neutral item in the verified replay. Preserve raw slot numbers for other builds. First observation in slots 0–5 proves placement there; it does not establish expiry of a backpack activation delay. Stash possession is not courier delivery. Consumed upgrades such as Shard and passive items must not be marked unused just because the combat log has no item cast.

On combined items, `m_flPurchaseTime` can retain the first component's purchase time. `m_flAssembledTime` can also change later. Use the first completed-item combat `PURCHASE` event and the first matching inventory observation as separate evidence, preserving their timestamps. Do not rewrite completion using a later snapshot. `ITEM` events record a use, not successful damage, survival or a won fight; those require separate outcome evidence.

Gold combat events retain signed `value` and numeric `goldReason`. The stream does not necessarily contain passive-income or purchase-spending events, so it cannot alone reconcile the wallet. Keep earned gold, sale refunds, losses and final net worth separate. Player resource income counters provide a separate reconciliation source. The [Valve schema dump of gold reasons](https://github.com/SteamTracking/GameTracking-Dota2/blob/master/DumpSource2/schemas/client/EDOTA_ModifyGold_Reason.h) distinguishes lane creeps (13), neutral creeps (14), hero kills (12), sales (6), and summons (22); older Panorama enum documentation uses different values after 13 and must not be applied blindly. Unknown reasons remain unknown.

A real 169,982,117-byte source was verified locally through the complete API upload → 33 chunks → Steam binding → worker → owner-authorized report flow in 35.51 seconds. The parser reached tick 152653; the report contained 121 selected-player events and 473 economy samples. This local integration check made no paid model calls and is not a server capacity benchmark.

Optional Gemini coaching uses the existing shared durable allowance and must cite report evidence. Provider failures leave the factual report available with coaching explicitly unavailable. This parser does not require video conversion, OpenDota, or a Steam login for an uploaded file. Arbitrary Match ID retrieval still requires a separately configured Steam Game Coordinator session; an ID alone is not a replay file.

Deploy `services/replay/Dockerfile` with the `replay-worker` Compose service. The pilot stops the old video worker before starting it, preserving the VM memory budget. Logs contain job IDs and fixed failure codes, never full rosters, raw parser stderr, prompts or secrets.

## Native decoder incident correction

The first container deployment could import the parser but failed before reading a packet because Snappy attempted to extract executable native code into `/tmp`, which is mounted `noexec`. The owner upload was intact. Bootstrap now extracts the native ELF library from the checksum-verified Snappy JAR into the root-owned, read-only image. Both worker parsing and its startup test load that fixed library path. `/tmp` remains `noexec`.

The deployment gate performs a real synthetic compression/decompression roundtrip under the same non-root UID, read-only root, noexec tmpfs, memory, CPU and process limits as production. Worker heartbeat starts only after this succeeds. Native library, resource and storage failures receive separate fixed error codes; raw parser error text is never published in logs.
