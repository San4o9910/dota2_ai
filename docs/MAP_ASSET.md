# Original game map and replay coordinates

The displayed background is the original7.41 game raster uploaded by Buny154
on10July2026 to [Liquipedia](https://liquipedia.net/commons/File:Game_map_7.41.jpg).
It matches the demo's patch. The7.39 image in the user's screenshot is a visual
reference, not the source for7.41 gameplay overlays.

- Bundled: `public/maps/7.41/game-map.jpg`,2166×2048,1,048,406bytes.
- [Original server thumbnail](https://liquipedia.net/commons/images/thumb/0/07/Game_map_7.41.jpg/2166px-Game_map_7.41.jpg)
- [Full raster](https://liquipedia.net/commons/images/0/07/Game_map_7.41.jpg),8909×8424.
- SHA256: `3f60db1ca1a1397c7a7e3fb3bd78c81370aacb17088e7b9518d62314ba31ca35`.
- Image credit: Buny154/Liquipedia, ©Valve Corporation. The page describes Valve's
  permission for Liquipedia; it is not an ISC or CC-licensed raster. Do not
  conflate the raster with the ISC coordinate data attributed in LICENSE.txt.

The image is copied without redrawing, color changes or local resampling.
The old generated terrain-color canvas is removed. Keep natural aspect2166/2048.

## Display calibration

`lib/replay/game-map-calibration.json` retains source URLs, image hash, ten
measured tower/ancient anchors, two independent Twin Gate check points and fit
residuals. `map-state.ts` applies the same transform to all overlays:

```
pixelX = 0.1112410929658031 * worldX + 1055.2606396150288
pixelY = -0.11164212900641522 * worldY + 1079.8155559442366
leftPercent = pixelX / 2166 * 100
topPercent = pixelY / 2048 * 100
```

Fit RMS3.15pixels; largest anchor residual5.45pixels. Independent gate checks
are4.13/2.64pixels. This is approximate display calibration, not a claim of
pixel-exact game-coordinate extraction. Old terrain bounds(-10464…10400) must
not be reused for this camera raster. OpenDota grid first becomes world using
`(grid-128)*128`.

## State overlays

Ward lifetimes use matching ehandle placement/removal entries. Before placement
a ward is hidden. Without removal evidence its activity remains unknown.
Building kills use target keys, not the killer's team. Generic T4 deaths remain
individually ambiguous after the first event and both destroyed after the next.
Absent events do not prove standing buildings when the journal is incomplete.

The raster contains static buildings/trees. Standing/destroyed/unknown replay
states are separate visible markers. The image itself is not destructible world
state. Exact team fog, dynamic trees and player camera remain unavailable.
