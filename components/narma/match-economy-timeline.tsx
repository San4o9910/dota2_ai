"use client";
import {useState,type PointerEvent} from "react";
import heroCatalog from "@/app/data/hero-catalog.json";
import {gameTimeLabel} from "@/components/narma/replay-map";
import {fightAtTime,fightGoldResult,sampleAtTime,timeFraction,timelineTicks,type TimelineFight,type TimelineSample} from "@/lib/replay/economy-timeline";

const format=(n:number|null|undefined)=>n===null||n===undefined?"Нет данных":`${n<0?"−":n>0?"+":""}${Math.abs(n).toLocaleString("ru-RU")}`;
const lead=(n:number|null|undefined)=>n===null||n===undefined?"Нет данных":n===0?"Равенство":`${n>0?"Radiant":"Dire"} +${Math.abs(n).toLocaleString("ru-RU")}`;

export default function MatchEconomyTimeline({samples,fights,duration,time,onSeek,goldBasis="total_earned"}:{
  samples:readonly TimelineSample[];fights:readonly TimelineFight[];duration:number;time:number;
  onSeek:(t:number)=>void;goldBasis?:"total_earned"|"net_worth";
}) {
  const [zoom,setZoom]=useState(false);
  const active=fightAtTime(fights,time),sample=sampleAtTime(samples,time);
  const earliest=Math.min(0,...fights.map(f=>f.startSeconds),...samples.map(s=>s.timeSeconds));
  const start=zoom&&active?Math.max(earliest,active.startSeconds-90):earliest;
  const end=zoom&&active?Math.min(duration,active.endSeconds+90):duration;
  const width=920,left=58,right=900,top=25,bottom=235,zero=130;
  const x=(t:number)=>left+timeFraction(t,start,end)*(right-left);
  const visible=samples.filter(s=>s.timeSeconds>=start-60&&s.timeSeconds<=end+60);
  const max=Math.max(1000,Math.ceil(Math.max(...visible.flatMap(s=>[Math.abs(s.radiantGoldAdvantage??0),Math.abs(s.radiantXpAdvantage??0)]),0)/1000)*1000);
  const y=(v:number)=>zero-v/max*(bottom-top)/2;
  const path=(field:"radiantGoldAdvantage"|"radiantXpAdvantage")=>{
    let previous:number|null=null;return samples.map(s=>{
      if(s[field]===null){previous=null;return "";}
      const command=previous===null||s.timeSeconds-previous>60?"M":"L";previous=s.timeSeconds;
      // Values outside the chosen range are clipped, not accumulated on its edges.
      const px=left+(s.timeSeconds-start)/(end-start)*(right-left);
      return `${command}${px.toFixed(2)},${y(s[field]!).toFixed(2)}`;
    }).join(" ");
  };
  const result=active?fightGoldResult(active):null;
  function seekFromPointer(event:PointerEvent<SVGSVGElement>) {
    if(event.button!==0)return;
    const rect=event.currentTarget.getBoundingClientRect();const px=(event.clientX-rect.left)/rect.width*width;
    onSeek(Math.round(start+Math.max(0,Math.min(1,(px-left)/(right-left)))*(end-start)));
  }
  return <div className="economy-timeline">
    <div className="economy-timeline-controls">
      <label>Драка <select aria-label="Выбрать драку по времени" value={active?.id??""} onChange={e=>{const f=fights.find(f=>f.id===e.target.value);if(f)onSeek(f.startSeconds);}}>
        <option value="" disabled>Выберите интервал</option>{fights.map(f=><option key={f.id} value={f.id}>{gameTimeLabel(f.startSeconds)}–{gameTimeLabel(f.endSeconds)}</option>)}
      </select></label>
      <button type="button" disabled={!active} aria-pressed={zoom} onClick={()=>setZoom(!zoom)}>{zoom?"Весь матч":"Приблизить драку"}</button>
      <span>Курсор · <strong>{gameTimeLabel(time)}</strong></span>
    </div>
    <div className="chart-legend">
      <span className="resource-readout gold"><i aria-hidden="true"/><span><small>Gold · {sample?`срез ${gameTimeLabel(sample.timeSeconds)}`:"нет среза"}</small><strong>{lead(sample?.radiantGoldAdvantage)}</strong></span></span>
      <span className="resource-readout xp"><i aria-hidden="true"/><span><small>XP · {sample?`срез ${gameTimeLabel(sample.timeSeconds)}`:"нет среза"}</small><strong>{lead(sample?.radiantXpAdvantage)}</strong></span></span>
    </div>
    <p className="chart-scale-note">Общая шкала · Radiant выше нуля, Dire ниже. Gold — {goldBasis==="net_worth"?"стоимость предметов и запас золота":"заработанное золото"}.</p>
    <div className="chart-scroll" role="region" aria-label="Прокручиваемый график Gold, XP и драк по времени матча" tabIndex={0}>
      <svg viewBox="0 0 920 340" className="resource-chart timed-resource-chart" onPointerDown={seekFromPointer} aria-label="Выберите время на графике или интервал драки">
        {active&&<rect x={x(active.startSeconds)} y={top} width={Math.max(1,x(active.endSeconds)-x(active.startSeconds))} height={bottom-top} className="fight-time-highlight"/>}
        {[-1,-.5,0,.5,1].map(t=><g key={t}><line x1={left} x2={right} y1={y(max*t)} y2={y(max*t)} className={t===0?"chart-zero":"chart-grid"}/><text x={left-8} y={y(max*t)+4} textAnchor="end" className="chart-tick">{max*t===0?"0":`${max*t>0?"+":"−"}${Math.abs(max*t/1000).toLocaleString("ru-RU")}k`}</text></g>)}
        {timelineTicks(start,end).map(t=><g key={t}><line x1={x(t)} x2={x(t)} y1={top} y2={285} className="timeline-time-grid"/><text x={x(t)} y={309} textAnchor={t===start?"start":t===end?"end":"middle"} className="chart-tick">{gameTimeLabel(t)}</text></g>)}
        <svg x={left} y={top} width={right-left} height={bottom-top} viewBox={`${left} ${top} ${right-left} ${bottom-top}`} overflow="hidden">
          <path d={path("radiantGoldAdvantage")} className="chart-line gold"/><path d={path("radiantXpAdvantage")} className="chart-line xp"/>
        </svg>
        <line x1={x(time)} x2={x(time)} y1={top} y2={285} className="chart-cursor"/>
        <text x={x(time)} y={16} textAnchor={x(time)>right-45?"end":x(time)<left+45?"start":"middle"} className="timeline-cursor-label">{gameTimeLabel(time)}</text>
        <text x={left-8} y={274} textAnchor="end" className="chart-tick">Драки</text>
        <line x1={left} x2={right} y1={268} y2={268} className="chart-grid"/>
        {fights.filter(f=>f.endSeconds>=start&&f.startSeconds<=end).map(f=>{
          const winner=fightGoldResult(f).side;return <rect key={f.id} data-fight-start={f.startSeconds} data-fight-end={f.endSeconds} x={x(f.startSeconds)} y={257} width={Math.max(4,x(f.endSeconds)-x(f.startSeconds))} height={22} rx={3}
            className={`timed-fight-marker ${winner==="Radiant"?"radiant":winner==="Dire"?"dire":"unknown"} ${active?.id===f.id?"active":""}`}
            role="button" tabIndex={0} aria-label={`Драка ${gameTimeLabel(f.startSeconds)}–${gameTimeLabel(f.endSeconds)}; Radiant ${format(f.radiant.goldDelta)}, Dire ${format(f.dire.goldDelta)} золота`}
            aria-pressed={active?.id===f.id} onPointerDown={e=>{e.stopPropagation();onSeek(f.startSeconds);}} onKeyDown={e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();onSeek(f.startSeconds);}}}/>;
        })}
      </svg>
    </div>
    <label className="economy-time-scrubber">Время · {gameTimeLabel(time)}<input type="range" aria-label="Время карты и графика" min={earliest} max={duration} step={1} value={time} onChange={e=>onSeek(Number(e.target.value))}/></label>
    {active&&result?<section className="selected-fight-result" aria-label="Результат выбранной драки">
      <div className="selected-fight-title"><div><p className="eyebrow">Итог интервала</p><h4>Драка {gameTimeLabel(active.startSeconds)}–{gameTimeLabel(active.endSeconds)}</h4></div><div className="fight-boundary-actions"><button type="button" onClick={()=>onSeek(active.startSeconds)}>К началу · {gameTimeLabel(active.startSeconds)}</button><button type="button" onClick={()=>onSeek(active.endSeconds)}>К концу · {gameTimeLabel(active.endSeconds)}</button></div></div>
      <div className="fight-team-gold">
        {(["radiant","dire"] as const).map(side=><div key={side} className={`fight-team-result ${side}`}><span>{side==="radiant"?"Radiant":"Dire"}</span><strong>{format(active[side].goldDelta)} <small>Gold</small></strong><p>{format(active[side].xpDelta)} XP · Убийств: {active[side].kills??"нет данных"} · Смертей: {active[side].deaths??"нет данных"}</p></div>)}
      </div>
      <p className="fight-result-difference">{result.difference===null?"Сравнение команд недоступно: нет полного изменения золота.":result.difference===0?"Изменение золота одинаковое у обеих команд.":<>По изменению золота выигрывает <strong>{result.side}</strong>. Разница изменений: <strong>{Math.abs(result.difference).toLocaleString("ru-RU")} Gold</strong>.</>}</p>
      <p className="fine-print">Показано изменение золота за весь интервал. Награды за убийства отдельно не выделены.</p>
      {active.players?.length?<details className="fight-player-breakdown"><summary>Золото по героям</summary><table><thead><tr><th>Герой</th><th>Команда</th><th>Gold</th><th>XP</th></tr></thead><tbody>{[...active.players].sort((a,b)=>(b.goldDelta??-Infinity)-(a.goldDelta??-Infinity)).map(p=><tr key={p.playerSlot}><td>{p.heroId?(heroCatalog as Record<string,{name:string}>)[String(p.heroId)]?.name??`Герой ${p.heroId}`:`Игрок ${p.playerSlot<128?p.playerSlot+1:p.playerSlot-122}`}</td><td>{p.playerSlot<128?"Radiant":"Dire"}</td><td>{format(p.goldDelta)}</td><td>{format(p.xpDelta)}</td></tr>)}</tbody></table></details>:<p className="fine-print">В этом сохранённом примере нет распределения золота по героям.</p>}
    </section>:<p className="fine-print">Выберите интервал драки на графике или в списке, чтобы сравнить золото команд.</p>}
  </div>;
}
