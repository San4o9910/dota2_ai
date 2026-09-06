# Independent Clarity replay probe

Research CLI for a future isolated replay worker. It imports **Clarity 4.0.1 directly**. No OpenDota API, OpenDota parser, HTTP calls, AI service, transcript, or video decoding takes place while the replay runs.

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

- SHA-256, file metadata, match ID from the epilogue, build/network protocol, playback ticks, and final tick reached. Metadata player count only; no account IDs or player names are printed.
- Separate creation, state change, network scope enter/leave, and explicit deletion observations for placed ward NPCs and actual `CDOTA_BaseNPC_Tower` entities. Ward inventory items and Watch Towers are excluded.
- Entity handle, index **and serial**, raw owner ID/handle, team, health, life state, exact building entity name, raw cell/offset positions, and source creation time when available.
- Combat-log deaths for towers/wards, with their own authoritative combat timestamps. No forced handle match is invented where the combat log lacks a unique entity handle.
- Demo tick, server tick, tick interval, recorded pause fields, start time, and a **derived** game-clock estimate. `matchTime` stays absent when no direct networked game-time property exists. The derived estimate is separately named and needs in-game validation, especially across pauses.

## Lifecycle rules for integration

1. `CDOTA_NPC_Observer_Ward` and `CDOTA_NPC_Observer_Ward_TrueSight` are placed NPCs. `CDOTA_Item_ObserverWard` and `CDOTA_Item_SentryWard` are inventory items and must not become map ward markers.
2. Hide a ward when its confirmed life state first becomes dying/dead. **Do not wait for entity deletion**: it can occur several seconds after the ward stopped granting vision. Keep expiration versus attack destruction unknown until independently supported. `scope_left` is never a ward death or team-visibility fact.
3. Resolve `m_pEntity.m_nameStringTableIndex` through `EntityNames` for tower identities. `m_iUnitNameIndex` uses a different indexing domain and must not be used with that table. The exact `tower4_top` and `tower4_bot` names keep both base towers separate.
4. Preserve raw cell/offset coordinates until a patch-specific map transform is validated. Do not infer world coordinates or minimap alignment from this probe alone.
5. Do not use metadata roster order or raw player owner IDs as canonical player slots. This prototype does not implement profile binding, player slot resolution, hero movement, economy, or fog-of-war.

## Real-file verification (2026-09-06)

An owner-provided 169,982,117-byte Source 2 replay was parsed locally through final tick **152653**, with 152654 tick callbacks, 76312 non-synthetic ticks, and build **10836**. Selected event handlers found:

- **81 placed ward NPCs**: 49 Observer and 32 TrueSight. All 81 have explicit life-state transitions and subsequent deletion.
- **22 actual towers**, including separately identified T1/T2/T3 and both T4s per team. Eighteen have life-state transitions and subsequent deletion.
- **99 ward/tower combat-log deaths** and 2261 tower state changes.

In the validated run, elapsed wall time was **5.84 seconds** and peak resident memory **799008 KiB**. This is one-file prototype timing, not a capacity benchmark or production guarantee. All 81 ward deletions lagged the first dying/dead observation by **5.8–10.07 seconds**, demonstrating why deletion must not define the end of ward vision.

Across the 99 combat deaths, the server-tick-derived clock differed from the combat timestamp by between approximately **-0.000082 and +0.033561 seconds**. This replay reported no paused ticks; pause correction remains unvalidated. No matching Dota-client/video validation has been performed. Parsing is not an AI coaching report, and no live website worker has been connected by this prototype.

Raw output remains outside Git. Only these reusable sources and dependency lock should be integrated into the project.

## Primary references

- [Clarity and Maven coordinates](https://github.com/skadistats/clarity)
- [Clarity examples and lifecycle callbacks](https://github.com/skadistats/clarity-examples)
- [Clarity 4.0.1 POM](https://repo.maven.apache.org/maven2/com/skadistats/clarity/4.0.1/clarity-4.0.1.pom)
- [Clarity protobuf 6.1 POM](https://repo.maven.apache.org/maven2/com/skadistats/clarity-protobuf/6.1/clarity-protobuf-6.1.pom)

Dependency coordinates, download URLs, versions, and SHA-256 hashes are pinned in `dependencies.lock.json`. Clarity is BSD-licensed; retain dependency licenses when distributing artifacts.
