# Exact team vision: current implementation boundary

The requested in-game fog is not implemented. The map explicitly identifies
itself as a full-map view with no terrain visibility data. A team ward filter is
not a fog-of-war mode. Do not enable a capability flag, draw visibility circles
or claim engine parity from the existing aggregate data.

## What was inspected

- The current adapter emits sampled hero coordinates/alive state, wards and
  building events. It does not export terrain masks, per-team hero visibility,
  dynamic tree geometry or all vision sources. Samples may be farther apart
  than five seconds after bounded compaction.
- The uploaded Source 2 replay's send-table schemas were inspected read-only.
  They contain temporary vision sources, blocker regions, tree-state fields
  and team NPC visibility bitsets. A ready terrain bitmap/chunk stream was not
  found in those schemas or the checked protocol definitions. Schema presence
  is not a decoded, validated visibility timeline.
- `CDOTA_DataNonSpectator.m_bNPCVisibleState` is not established as a terrain
  bitmap; entity-index interpretation must be verified before using it.
- `CPlayerVisibility` contains atmospheric fog parameters. It must not be used
  as a team's gameplay visibility mask.

Primary implementation references:

- [Pinned OpenDota parser](https://github.com/odota/parser/blob/de9d6b260b15427fcaec16c061884f18ea3a6b14/src/main/java/opendota/Parse.java)
- [Clarity parser](https://github.com/skadistats/clarity)
- [Engine temporary-viewer schema](https://github.com/SteamTracking/GameTracking-Dota2/blob/master/DumpSource2/schemas/server/TempViewerInfo_t.h)
- [Engine blocker schema](https://github.com/SteamTracking/GameTracking-Dota2/blob/master/DumpSource2/schemas/server/CFoWBlockerRegion.h)
- [Engine team-state schema](https://github.com/SteamTracking/GameTracking-Dota2/blob/master/DumpSource2/schemas/server/CDOTA_DataNonSpectator.h)

The engine-schema links track upstream master and are research references, not
version-pinned runtime dependencies or substitutes for the replay send tables.

## Required work before rendering

1. Extract vision sources, temporary viewers, blocker/tree changes and team
   entity visibility through Clarity on one shared game-clock timeline.
2. Obtain terrain heights, obstruction geometry and tree-index mapping from
   the same version of the actual Dota level. The JPEG background does not
   contain this data.
3. Establish a working engine-backed exporter or independently verify the
   reconstruction against Dota playback. No engine or exporter is available in
   the current development environment. The documented VScript
   [IsLocationVisible API](https://developer.valvesoftware.com/wiki/Dota_2_Workshop_Tools/Scripting/API)
   is not a confirmed API for ordinary recorded-match playback.
4. Validate both teams at cliffs, tree edges and tree destruction, day/night
   changes, ward expiry/dewarding, temporary ability vision, pause and seek.
5. Then define a bounded, patch-tagged mask timeline and renderer. Require
   verified frame coverage for the selected time, retain no future visibility
   on rewind, and hide enemy units and unobserved state changes independently
   of terrain shading. Keep true sight/invisibility separate from terrain
   visibility; do not reveal enemy wards from a terrain mask alone.

This document records a blocker and verification requirements. It is not a
working export integration, and the current release does not claim exact fog.
