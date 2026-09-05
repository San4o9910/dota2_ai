"use client";
import { useState } from "react";
import TerrainMap from "@/components/narma/terrain-map";
import { MAP_BUILDINGS, buildingStateAt, wardStateAt, worldToPercent, type ReplayMap } from "@/lib/replay/map-state";

export function gameTimeLabel(t: number) { const value=Math.abs(Math.floor(t));return `${t<0 ? "−" : ""}${Math.floor(value/60)}:${String(value%60).padStart(2,"0")}`; }

export default function ReplayMapView({data,time,perspective="all",structures=true,wards=true}: {
  data: ReplayMap; time:number; perspective?:"all"|"radiant"|"dire";structures?:boolean;wards?:boolean;
}) {
  const [selected,setSelected] = useState<string|null>(null);
  const [failed,setFailed] = useState(false);
  const [history,setHistory] = useState(false);
  const [zoom,setZoom] = useState(1);
  const visibleWards = data.wards.filter(w=>w.placedAt<=time && (perspective==="all"||w.side===perspective) && (history||wardStateAt(w,time)==="active"||wardStateAt(w,time)==="unknown"));
  const currentHeroes=new Map<number,NonNullable<ReplayMap["heroPositions"]>[number]>();
  for(const p of data.heroPositions??[])if(p.time<=time && (!currentHeroes.has(p.playerSlot)||currentHeroes.get(p.playerSlot)!.time<p.time))currentHeroes.set(p.playerSlot,p);
  const building=MAP_BUILDINGS.find(b=>b.key===selected);
  const buildingState=building ? buildingStateAt(building.key,data.buildings,time,data.buildingEventsComplete) : null;
  const ward=data.wards.find(w=>w.id===selected);
  return <div className="replay-map-shell">
    <div className="replay-map-toolbar">
      <span>{gameTimeLabel(time)} · {perspective==="all" ? "Общий обзор" : perspective==="radiant" ? "Варды Radiant" : "Варды Dire"}</span>
      <label><input type="checkbox" checked={history} onChange={e=>setHistory(e.target.checked)}/> История вардов</label>
      <button type="button" onClick={()=>setZoom(z=>z===1 ? 1.5 : 1)} aria-label={zoom===1 ? "Увеличить карту" : "Показать всю карту"}>{zoom===1 ? "1.5×" : "1×"}</button>
    </div>
    <div className="replay-map-scroll" tabIndex={0} aria-label="Карта матча; при увеличении можно прокручивать">
      <div className="map-stage replay-map-stage" style={{width:`${zoom*100}%`,aspectRatio:"1"}}>
        {!failed ? <TerrainMap onError={()=>setFailed(true)}/> : <p className="map-missing" role="status">Не удалось загрузить карту. События доступны в хронологии.</p>}
        {!failed && structures && MAP_BUILDINGS.map(b=>{
          const state=buildingStateAt(b.key,data.buildings,time,data.buildingEventsComplete);
          const pos=worldToPercent(b.x,b.y);
          const label=`${b.side==="radiant" ? "Radiant" : "Dire"} · ${b.label} · ${state.state==="destroyed" ? `разрушена ${gameTimeLabel(state.destroyedAt!)}` : state.state==="standing" ? "стоит" : "нет полного журнала разрушений"}`;
          return <button type="button" key={b.key} className={`replay-building ${b.side} ${state.state} ${b.kind}`} style={{left:`${pos.left}%`,top:`${pos.top}%`}} onClick={()=>setSelected(b.key)} title={label} aria-label={label} aria-pressed={selected===b.key}>{state.state==="destroyed" ? "×" : b.kind==="ancient" ? "A" : b.label.slice(1,2)}</button>;
        })}
        {!failed && wards && visibleWards.map(w=>{
          const state=wardStateAt(w,time);const pos=worldToPercent(w.x,w.y);
          const label=`${w.kind==="observer" ? "Observer" : "Sentry"} · ${w.side} · установлен ${gameTimeLabel(w.placedAt)}${state==="unknown" ? "; время снятия неизвестно" : state==="removed" ? "; снят" : "; активен"}`;
          return <button type="button" key={w.id} className={`replay-ward ${w.side} ${w.kind} ${state}`} style={{left:`${pos.left}%`,top:`${pos.top}%`}} title={label} aria-label={label} aria-pressed={selected===w.id} onClick={()=>setSelected(w.id)}>{w.kind==="observer" ? "●" : "◇"}</button>;
        })}
        {!failed&&[...currentHeroes.values()].filter(p=>p.alive && time-p.time<=30 && (perspective==="all"||(p.playerSlot<128 ? "radiant" : "dire")===perspective)).map(p=>{const pos=worldToPercent(p.x,p.y);return <span key={p.playerSlot} className={`replay-hero ${p.playerSlot<128 ? "radiant" : "dire"}`} style={{left:`${pos.left}%`,top:`${pos.top}%`}} title={`Игрок ${p.playerSlot<128?p.playerSlot+1:p.playerSlot-122}; срез ${gameTimeLabel(p.time)}`}>{p.playerSlot<128?p.playerSlot+1:p.playerSlot-122}</span>;})}
        <span className="map-team-label radiant">RADIANT</span><span className="map-team-label dire">DIRE</span>
      </div>
    </div>
    <div className="replay-map-legend"><span className="radiant-text">● Radiant</span><span className="dire-text">● Dire</span><span>× Разрушена</span><span>○ Нет времени снятия</span></div>
    <div className="replay-map-detail" role="status">
      {building && buildingState ? <p><strong>{building.side==="radiant" ? "Radiant" : "Dire"} · {building.label}</strong> — {buildingState.state==="destroyed" ? `разрушена в ${gameTimeLabel(buildingState.destroyedAt!)}` : buildingState.state==="standing" ? "на выбранный момент стоит" : "в доступном журнале нет полного состояния этой постройки"}.</p>
        : ward ? <p><strong>{ward.kind==="observer" ? "Observer Ward" : "Sentry Ward"}</strong> · поставлен {gameTimeLabel(ward.placedAt)}. {ward.removedAt===null ? "Время снятия неизвестно; активность не подтверждена." : `Снят ${gameTimeLabel(ward.removedAt)}.`}</p>
        : <p>Нажмите на башню или вард, чтобы увидеть событие.</p>}
      <p className="fine-print">Рельеф и исходные деревья — патч 7.41. Туман войны недоступен в сводке. Варды показаны по журналу установки и снятия; это не вся область обзора команды.</p>
    </div>
  </div>;
}
