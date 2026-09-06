import calibration from "@/lib/replay/game-map-calibration.json";
import { z } from "zod";

export const GAME_MAP_ASPECT_RATIO=`${calibration.thumbnailWidth}/${calibration.thumbnailHeight}`;
export const MAP_WORLD_BOUND = 12000;
export const MapSideSchema = z.enum(["radiant", "dire"]);
const coordinate = z.number().finite().min(-MAP_WORLD_BOUND).max(MAP_WORLD_BOUND);
const gameTime = z.number().finite().min(-600).max(43200);

export const MapWardSchema = z.object({
  id: z.string().max(100), kind: z.enum(["observer", "sentry"]), side: MapSideSchema,
  x: coordinate, y: coordinate, placedAt: gameTime, removedAt: gameTime.nullable(),
}).strict().refine(w => w.removedAt === null || w.removedAt >= w.placedAt);
export type MapWard = z.infer<typeof MapWardSchema>;
export const BuildingEventSchema = z.object({
  key: z.string().regex(/^npc_dota_(?:goodguys|badguys)_(?:tower(?:[1-3]_(?:top|mid|bot)|4(?:_(?:top|mid|bot)[12]?)?)|(?:melee|range)_rax_(?:top|mid|bot)|fort)$/),
  destroyedAt: gameTime,
}).strict();
export const ReplayMapSchema = z.object({
  schemaVersion: z.literal("replay-map.v1"),
  wards: z.array(MapWardSchema).max(2048),
  buildings: z.array(BuildingEventSchema).max(64),
  wardLifetimesComplete: z.boolean(),
  buildingEventsComplete: z.boolean(),
  // Aggregate APIs do not supply terrain visibility. A future parser must
  // provide actual sampled visibility, never synthesized circles around wards.
  terrainVision: z.literal("unavailable"),
  heroPositions:z.array(z.object({playerSlot:z.number().int().refine(s=>(s>=0&&s<=4)||(s>=128&&s<=132)),time:gameTime,x:coordinate,y:coordinate,alive:z.boolean()}).strict()).max(5000).optional(),
}).strict();
export type ReplayMap = z.infer<typeof ReplayMapSchema>;

export function worldToPercent(x: number, y: number) {
  // Pinned source image and crop metadata: docs/MAP_ASSET.md.
  const c=calibration.coefficients;
  return {left:(c.pixelXScale*x+c.pixelXOffset)/calibration.thumbnailWidth*100,
    top:(c.pixelYScale*y+c.pixelYOffset)/calibration.thumbnailHeight*100};
}
export function gridToWorld(x: number, y: number) {
  return { x: (x - 128) * 128, y: (y - 128) * 128 };
}
export function wardStateAt(ward: MapWard, time: number) {
  if (time < ward.placedAt) return "not_placed" as const;
  if (ward.removedAt !== null) return time < ward.removedAt ? "active" as const : "removed" as const;
  return "unknown" as const;
}

export function activeWardsAt(wards: MapWard[], time: number, perspective: "all" | "radiant" | "dire" = "all") {
  return wards.filter(ward => wardStateAt(ward,time) === "active" && (perspective === "all" || ward.side === perspective));
}

export type MapBuilding = { key: string; x: number; y: number; side: "radiant" | "dire"; label: string; kind: "tower" | "ancient" };
// Positions from the pinned 7.41 mapdata referenced in docs/MAP_ASSET.md.
const towerPositions: Array<[string, number, number, string]> = [
  ["goodguys_tower1_top",-6336,1856,"T1 · верх"], ["goodguys_tower2_top",-6501,-872,"T2 · верх"], ["goodguys_tower3_top",-6592,-3408,"T3 · верх"],
  ["goodguys_tower1_mid",-1544,-1408,"T1 · центр"], ["goodguys_tower2_mid",-3190,-2926,"T2 · центр"], ["goodguys_tower3_mid",-4640,-4144,"T3 · центр"],
  ["goodguys_tower1_bot",4860,-6379,"T1 · низ"], ["goodguys_tower2_bot",-360,-6256,"T2 · низ"], ["goodguys_tower3_bot",-3952,-6112,"T3 · низ"],
  ["goodguys_tower4_top",-5712,-4864,"T4"], ["goodguys_tower4_bot",-5392,-5192,"T4"],
  ["badguys_tower1_top",-5275,6036,"T1 · верх"], ["badguys_tower2_top",-128,6016,"T2 · верх"], ["badguys_tower3_top",3552,5776,"T3 · верх"],
  ["badguys_tower1_mid",524,652,"T1 · центр"], ["badguys_tower2_mid",2496,2112,"T2 · центр"], ["badguys_tower3_mid",4272,3759,"T3 · центр"],
  ["badguys_tower1_bot",6269,-2240,"T1 · низ"], ["badguys_tower2_bot",6400,384,"T2 · низ"], ["badguys_tower3_bot",6336,3032,"T3 · низ"],
  ["badguys_tower4_top",4944,4776,"T4"], ["badguys_tower4_bot",5280,4432,"T4"],
];
export const MAP_BUILDINGS: MapBuilding[] = towerPositions.map(([key,x,y,label]) => ({key:`npc_dota_${key}`,x,y,label,side:key.startsWith("good") ? "radiant" : "dire",kind:"tower"}));
MAP_BUILDINGS.push(
  {key:"npc_dota_goodguys_fort",x:-5920,y:-5352,side:"radiant",kind:"ancient",label:"Ancient"},
  {key:"npc_dota_badguys_fort",x:5528,y:5000,side:"dire",kind:"ancient",label:"Ancient"},
);
export function buildingStateAt(key: string, events: ReplayMap["buildings"], time: number, complete: boolean) {
  if (key.includes("_tower4_")) {
    const sharedKey=key.replace(/_tower4_.+$/, "_tower4");
    const shared=events.filter(e=>e.key===sharedKey && e.destroyedAt<=time).sort((a,b)=>a.destroyedAt-b.destroyedAt);
    if(shared.length>=2)return {state:"destroyed" as const,destroyedAt:shared[1].destroyedAt};
    if(shared.length===1)return {state:"unknown" as const,destroyedAt:null};
  }
  const event = events.filter(e => e.key === key).sort((a,b) => a.destroyedAt-b.destroyedAt)[0];
  if (event && event.destroyedAt <= time) return {state:"destroyed" as const, destroyedAt:event.destroyedAt};
  return {state: event || complete ? "standing" as const : "unknown" as const, destroyedAt:null};
}
