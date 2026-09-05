"use client";
import {useState} from "react";
import type {AnalysisDetail} from "@/lib/analyses/contracts";
import ReplayMapView,{gameTimeLabel} from "@/components/narma/replay-map";

export default function MatchReplayPanel({detail,time,onSeek}:{detail:AnalysisDetail;time:number;onSeek:(t:number)=>void}) {
  const [perspective,setPerspective]=useState<"all"|"radiant"|"dire">("all");
  const match=detail.match;
  const evidence=detail.evidenceBundle;
  const duration=match?.durationSeconds ?? evidence?.durationSeconds ?? 0;
  const economy=match?.economy ?? evidence?.evidence.filter(e=>e.kind==="economy"&&e.time?.type==="point").map(e=>({timeSeconds:e.time!.type==="point" ? e.time!.seconds : 0,radiantGoldAdvantage:e.values.find(v=>v.unit==="gold")?.value ?? null,radiantXpAdvantage:e.values.find(v=>v.unit==="xp")?.value ?? null})) ?? [];
  if(!duration) return null;
  const sample=economy.filter(e=>e.timeSeconds<=time).at(-1);
  const max=Math.max(1000,...economy.flatMap(e=>[Math.abs(e.radiantGoldAdvantage ?? 0),Math.abs(e.radiantXpAdvantage ?? 0)]));
  const earliest=Math.min(0,...(evidence?.evidence??[]).map(e=>e.time?.type==="point" ? e.time.seconds : e.time?.type==="window" ? e.time.startSeconds : 0));
  const x=(t:number)=>45+(t-earliest)/(duration-earliest)*620;
  const y=(value:number)=>110-value/max*80;
  const line=(field:"radiantGoldAdvantage"|"radiantXpAdvantage")=>{let gap=true;return economy.map(e=>{if(e[field]===null){gap=true;return "";}const s=`${gap ? "M" : "L"}${x(e.timeSeconds)},${y(e[field]!)}`;gap=false;return s;}).join(" ");};
  const value=(n:number|null|undefined)=>n===null||n===undefined ? "Нет данных" : `${n>=0?"+":""}${n.toLocaleString("ru-RU")}`;
  const events=evidence?.evidence.filter(e=>(e.kind==="fight"||e.kind==="objective")&&e.time!==null) ?? [];
  return <section className="dynamic-replay" id="match-replay" aria-label="Карта и ресурсы этого матча">
    <div className="dynamic-replay-header"><h3>Матч {detail.job.matchId}</h3><strong>{gameTimeLabel(time)}</strong></div>
    <div className="dynamic-replay-controls"><label>Показать <select value={perspective} onChange={e=>setPerspective(e.target.value as typeof perspective)}><option value="all">Обе команды</option><option value="radiant">Варды Radiant</option><option value="dire">Варды Dire</option></select></label></div>
    {match?.replayMap && match.patch==="7.41" ? <ReplayMapView data={match.replayMap} time={time} perspective={perspective}/> : <p className="fine-print">{match?.patch && match.patch!=="7.41" ? `Для патча ${match.patch} ещё нет проверенной подложки. События и экономика доступны ниже.` : "Для этого сохранённого разбора нет данных карты. События и экономика доступны ниже."}</p>}
    <label>Время матча · {gameTimeLabel(time)}<input type="range" min={earliest} max={duration} value={time} onChange={e=>onSeek(Number(e.target.value))}/></label>
    <div className="chart-legend"><span className="resource-readout gold">Gold <strong>{value(sample?.radiantGoldAdvantage)}</strong></span><span className="resource-readout xp">XP <strong>{value(sample?.radiantXpAdvantage)}</strong></span></div>
    <p className="fine-print">Общая шкала: Radiant выше нуля, Dire ниже. Gold — {match?.economyGoldBasis==="net_worth" ? "стоимость предметов и запас золота" : "заработанное золото"}. {sample ? `Срез ${gameTimeLabel(sample.timeSeconds)}.` : "На выбранную минуту нет замера."}</p>
    {economy.length>0 && <svg className="dynamic-economy" viewBox="0 0 690 225" role="img" aria-label="Gold и XP на общей временной шкале">
      {[-1,0,1].map(t=><g key={t}><line x1={45} x2={665} y1={y(max*t)} y2={y(max*t)} stroke="#ffffff20"/><text x={2} y={y(max*t)+4} fill="currentColor" fontSize={12}>{Math.round(max*t/1000)}k</text></g>)}
      <path d={line("radiantGoldAdvantage")} fill="none" stroke="#deb974" strokeWidth={2.5}/><path d={line("radiantXpAdvantage")} fill="none" stroke="#8dabe5" strokeWidth={2.5}/><line x1={x(time)} x2={x(time)} y1={24} y2={195} stroke="currentColor" strokeDasharray="4 4"/>
      <text x={45} y={220} fill="currentColor" fontSize={12}>{gameTimeLabel(earliest)}</text><text x={620} y={220} fill="currentColor" fontSize={12}>{gameTimeLabel(duration)}</text>
    </svg>}
    <div className="dynamic-events" aria-label="События матча">{events.map(e=>{const t=e.time!.type==="point" ? e.time!.seconds : e.time!.startSeconds;return <button key={e.id} type="button" onClick={()=>onSeek(t)}>{gameTimeLabel(t)} · {e.kind==="fight" ? "Драка" : e.id.includes("tower") ? "Башня" : e.id.includes("roshan") ? "Roshan" : e.id.includes("tormentor") ? "Tormentor" : "Событие"}</button>;})}</div>
  </section>;
}
