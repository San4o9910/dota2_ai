import { BuildingEventSchema, gridToWorld, MapWardSchema, ReplayMapSchema, type ReplayMap } from "@/lib/replay/map-state";

const record = (x: unknown): Record<string, unknown> | null => x && typeof x === "object" && !Array.isArray(x) ? x as Record<string, unknown> : null;
const list = (x: unknown): unknown[] => Array.isArray(x) ? x.slice(0,2048) : [];

/** Whitelist gameplay fields only: no player identity/chat/raw replay text. */
export function normalizeReplayMap(raw: { players: Array<Record<string, unknown>>; objectives?: unknown[] | null; duration: number; version?: number | null; _narma_hero_positions?:unknown }): ReplayMap {
  const wards: ReplayMap["wards"] = [];
  for (const player of raw.players) {
    for (const [kind, placementKey, removalKey] of [["observer","obs_log","obs_left_log"],["sentry","sen_log","sen_left_log"]] as const) {
      const removals = list(player[removalKey]).flatMap(x => record(x) ? [record(x)!] : []);
      for (const [index, value] of list(player[placementKey]).entries()) {
        const entry = record(value);
        if (!entry || typeof entry.x !== "number" || typeof entry.y !== "number" || typeof entry.time !== "number" || entry.time > raw.duration) continue;
        // Entity handle is the replay identity; coordinates alone may be reused.
        const removal = (typeof entry.ehandle === "number" || typeof entry.ehandle === "string")
          ? removals.filter(r => r.ehandle === entry.ehandle && typeof r.time === "number" && r.time >= (entry.time as number)).sort((a,b) => Number(a.time)-Number(b.time))[0]
          : null;
        const point = gridToWorld(entry.x,entry.y);
        const parsed = MapWardSchema.safeParse({id:`${player.player_slot}.${kind}.${index}`,kind,side:Number(player.player_slot)<128 ? "radiant" : "dire",...point,placedAt:entry.time,removedAt:removal && Number(removal.time)<=raw.duration ? removal.time : null});
        if (parsed.success) wards.push(parsed.data);
      }
    }
  }
  const buildings = list(raw.objectives).flatMap(value => {
    const event = record(value);
    if (event?.type !== "building_kill" || typeof event.time !== "number" || event.time > raw.duration) return [];
    const parsed = BuildingEventSchema.safeParse({key:event.key,destroyedAt:event.time});
    return parsed.success ? [parsed.data] : [];
  });
  const heroPositions=Array.isArray(raw._narma_hero_positions) ? raw._narma_hero_positions.slice(0,5000).flatMap(value=>{
    const p=record(value);if(!p||typeof p.time!=="number"||p.time<-600||p.time>raw.duration||typeof p.x!=="number"||typeof p.y!=="number")return [];
    return [{playerSlot:p.playerSlot,time:p.time,...gridToWorld(p.x,p.y),alive:p.alive}];
  }) : undefined;
  return ReplayMapSchema.parse({schemaVersion:"replay-map.v1",wards:wards.sort((a,b)=>a.placedAt-b.placedAt||a.id.localeCompare(b.id)).slice(0,2048),buildings:buildings.sort((a,b)=>a.destroyedAt-b.destroyedAt||a.key.localeCompare(b.key)),wardLifetimesComplete:wards.length>0 && wards.every(w=>w.removedAt!==null),buildingEventsComplete:!!raw.version && Array.isArray(raw.objectives),terrainVision:"unavailable",...(heroPositions ? {heroPositions} : {})});
}
