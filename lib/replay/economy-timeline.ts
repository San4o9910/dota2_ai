import type {NormalizedMatchV1} from "@/lib/analysis/contracts";

export type TimelineFight = NormalizedMatchV1["fights"][number];
export type TimelineSample = NormalizedMatchV1["economy"][number];

/** Keep all event coordinates in seconds, including the last partial minute. */
export function timeFraction(time:number,start:number,end:number) {
  return end>start ? Math.max(0,Math.min(1,(time-start)/(end-start))) : 0;
}

/** A cursor cannot silently select an upcoming fight. */
export function fightAtTime(fights:readonly TimelineFight[],time:number) {
  return fights.filter(f=>f.startSeconds<=time).sort((a,b)=>b.startSeconds-a.startSeconds)
    .find(f=>f.endSeconds>=time)
    ?? fights.filter(f=>f.startSeconds<=time).sort((a,b)=>b.startSeconds-a.startSeconds)[0]
    ?? null;
}

export function fightGoldResult(fight:TimelineFight) {
  const radiant=fight.radiant.goldDelta,dire=fight.dire.goldDelta;
  if(radiant===null||dire===null)return {radiant,dire,difference:null,side:null};
  const difference=radiant-dire;
  return {radiant,dire,difference,side:difference>0 ? "Radiant" : difference<0 ? "Dire" : "Равенство"};
}

export function sampleAtTime(samples:readonly TimelineSample[],time:number) {
  return samples.filter(s=>s.timeSeconds<=time).sort((a,b)=>b.timeSeconds-a.timeSeconds)[0]??null;
}

export function timelineTicks(start:number,end:number) {
  const span=end-start,step=span>1800?300:span>600?120:span>180?60:15;
  const ticks=[start];
  for(let t=Math.ceil(start/step)*step;t<end;t+=step)if(t>start+step*.2&&t<end-step*.25)ticks.push(t);
  ticks.push(end);return ticks;
}
