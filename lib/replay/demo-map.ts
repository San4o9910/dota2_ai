import { EVENTS, WARDS } from "@/app/data/match-8963624400";
import { gridToWorld, type ReplayMap } from "@/lib/replay/map-state";

export const DEMO_REPLAY_MAP: ReplayMap = {
  schemaVersion:"replay-map.v1",terrainVision:"unavailable",wardLifetimesComplete:false,buildingEventsComplete:false,
  wards:WARDS.map((w,index)=>({id:`demo.${index}`,kind:w.type==="obs" ? "observer" : "sentry",side:w.side==="R" ? "radiant" : "dire",...gridToWorld(w.x,w.y),placedAt:w.t,removedAt:null})),
  buildings:EVENTS.flatMap<{key:string;destroyedAt:number}>(e=>{
    if(e.type==="ancient") return [{key:"npc_dota_goodguys_fort",destroyedAt:e.t}];
    if(e.type!=="tower") return [];
    const m=/^T([1-4]) (Radiant|Dire) (top|mid|bot)$/.exec(e.title);
    return m ? [{key:`npc_dota_${m[2]==="Radiant" ? "goodguys" : "badguys"}_tower${m[1]}_${m[3]}`,destroyedAt:e.t}] : [];
  }),
};
