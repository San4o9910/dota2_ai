"use client";
import {useState} from "react";
import type {AnalysisDetail} from "@/lib/analyses/contracts";
import MatchEconomyTimeline from "@/components/narma/match-economy-timeline";
import ReplayMapView,{gameTimeLabel} from "@/components/narma/replay-map";

export default function MatchReplayPanel({detail,time,onSeek}:{detail:AnalysisDetail;time:number;onSeek:(t:number)=>void}) {
  const [perspective,setPerspective]=useState<"all"|"radiant"|"dire">("all");
  const match=detail.match;
  const evidence=detail.evidenceBundle;
  const duration=match?.durationSeconds ?? evidence?.durationSeconds ?? 0;
  const economy=match?.economy ?? evidence?.evidence.filter(e=>e.kind==="economy"&&e.time?.type==="point").map(e=>({timeSeconds:e.time!.type==="point" ? e.time!.seconds : 0,radiantGoldAdvantage:e.values.find(v=>v.unit==="gold")?.value ?? null,radiantXpAdvantage:e.values.find(v=>v.unit==="xp")?.value ?? null})) ?? [];
  if(!duration) return null;
  const fights=match?.fights??evidence?.evidence.filter(e=>e.kind==="fight"&&e.time?.type==="window").map(e=>{
    const metric=(key:string)=>e.values.find(v=>v.metric===key)?.value??null;
    const team=(side:string)=>({goldDelta:metric(`${side}_gold_delta`),xpDelta:metric(`${side}_xp_delta`),kills:metric(`${side}_kills`),deaths:metric(`${side}_deaths`),damage:metric(`${side}_damage`)});
    return {id:e.id,startSeconds:e.time!.type==="window"?e.time!.startSeconds:0,endSeconds:e.time!.type==="window"?e.time!.endSeconds:0,radiant:team("radiant"),dire:team("dire")};
  })??[];
  const events=evidence?.evidence.filter(e=>(e.kind==="fight"||e.kind==="objective")&&e.time!==null) ?? [];
  return <section className="dynamic-replay" id="match-replay" aria-label="Карта и ресурсы этого матча">
    <div className="dynamic-replay-header"><h3>Матч {detail.job.matchId}</h3><strong>{gameTimeLabel(time)}</strong></div>
    <div className="dynamic-replay-controls"><label>Показать <select value={perspective} onChange={e=>setPerspective(e.target.value as typeof perspective)}><option value="all">Обе команды</option><option value="radiant">Варды Radiant</option><option value="dire">Варды Dire</option></select></label></div>
    {match?.replayMap && match.patch==="7.41" ? <ReplayMapView data={match.replayMap} time={time} perspective={perspective}/> : <p className="fine-print">{match?.patch && match.patch!=="7.41" ? `Для патча ${match.patch} ещё нет проверенной подложки. События и экономика доступны ниже.` : "Для этого сохранённого разбора нет данных карты. События и экономика доступны ниже."}</p>}
    <MatchEconomyTimeline samples={economy} fights={fights} duration={duration} time={time} onSeek={onSeek} goldBasis={match?.economyGoldBasis}/>
    <div className="dynamic-events" aria-label="События матча">{events.map(e=>{const t=e.time!.type==="point" ? e.time!.seconds : e.time!.startSeconds;return <button key={e.id} type="button" onClick={()=>onSeek(t)}>{gameTimeLabel(t)} · {e.kind==="fight" ? "Драка" : e.id.includes("tower") ? "Башня" : e.id.includes("roshan") ? "Roshan" : e.id.includes("tormentor") ? "Tormentor" : "Событие"}</button>;})}</div>
  </section>;
}
