"use client";
import { useState } from "react";
import GameMapImage from "@/components/narma/game-map-image";
import { GAME_MAP_ASPECT_RATIO, MAP_BUILDINGS, buildingStateAt, activeWardsAt, worldToPercent, type ReplayMap } from "@/lib/replay/map-state";
import { MAP_CAMPS, CAMP_LABELS } from "@/lib/replay/map-camps";
import { WardGlyph, CampGlyph } from "@/components/narma/map-glyphs";

export function gameTimeLabel(t: number) { const value=Math.abs(Math.floor(t));return `${t<0 ? "−" : ""}${Math.floor(value/60)}:${String(value%60).padStart(2,"0")}`; }

export default function ReplayMapView({data,time,perspective="all",structures=true,wards=true,camps=true}: {
  data: ReplayMap; time:number; perspective?:"all"|"radiant"|"dire";structures?:boolean;wards?:boolean;camps?:boolean;
}) {
  const [selected,setSelected] = useState<string|null>(null);
  const [failed,setFailed] = useState(false);
  const [zoom,setZoom] = useState(1);
  const visibleWards = wards ? activeWardsAt(data.wards,time,perspective) : [];
  const currentHeroes=new Map<number,NonNullable<ReplayMap["heroPositions"]>[number]>();
  for(const p of data.heroPositions??[])if(p.time<=time && (!currentHeroes.has(p.playerSlot)||currentHeroes.get(p.playerSlot)!.time<p.time))currentHeroes.set(p.playerSlot,p);
  const building=structures ? MAP_BUILDINGS.find(b=>b.key===selected) : undefined;
  const buildingState=building ? buildingStateAt(building.key,data.buildings,time,data.buildingEventsComplete) : null;
  const ward=visibleWards.find(w=>w.id===selected);
  const camp=camps ? MAP_CAMPS.find(c=>c.id===selected) : undefined;
  return <div className="replay-map-shell">
    <div className="replay-map-toolbar">
      <span>{gameTimeLabel(time)} · {perspective==="all" ? "Все события" : perspective==="radiant" ? "Варды Radiant" : "Варды Dire"}</span>
      <button type="button" onClick={()=>setZoom(z=>z===1 ? 1.5 : 1)} aria-label={zoom===1 ? "Увеличить карту" : "Показать всю карту"}>{zoom===1 ? "1.5×" : "1×"}</button>
    </div>
    <p className="map-vision-status">Полная карта · туман войны недоступен: нет данных видимости территории.</p>
    <div className="replay-map-scroll" tabIndex={0} aria-label="Карта матча; при увеличении можно прокручивать">
      <div className="map-stage replay-map-stage" style={{width:`${zoom*100}%`,aspectRatio:GAME_MAP_ASPECT_RATIO}}>
        {!failed ? <GameMapImage onError={()=>setFailed(true)}/> : <p className="map-missing" role="status">Не удалось загрузить карту. События доступны в хронологии.</p>}
        {!failed && camps && MAP_CAMPS.map(c=>{
          const pos=worldToPercent(c.x,c.y);
          const label=`${CAMP_LABELS[c.tier]} · сторона ${c.side==="radiant" ? "Radiant" : "Dire"}`;
          return <button type="button" key={c.id} className={`replay-camp ${c.side}`} style={{left:`${pos.left}%`,top:`${pos.top}%`}} title={label} aria-label={label} aria-pressed={selected===c.id} onClick={()=>setSelected(c.id)}><CampGlyph tier={c.tier}/></button>;
        })}
        {!failed && structures && MAP_BUILDINGS.map(b=>{
          const state=buildingStateAt(b.key,data.buildings,time,data.buildingEventsComplete);
          const pos=worldToPercent(b.x,b.y);
          const label=`${b.side==="radiant" ? "Radiant" : "Dire"} · ${b.label} · ${state.state==="destroyed" ? `разрушена ${gameTimeLabel(state.destroyedAt!)}` : state.state==="standing" ? "стоит" : "нет полного журнала разрушений"}`;
          const tier=b.kind==="ancient" ? "A" : b.label.split(" · ")[0];
          const offset=b.key.includes("_tower4_") ? (b.key.endsWith("_top") ? "offset-top" : "offset-bottom") : "";
          return <button type="button" key={b.key} className={`replay-building ${b.side} ${state.state} ${b.kind} ${offset}`} style={{left:`${pos.left}%`,top:`${pos.top}%`}} onClick={()=>setSelected(b.key)} title={label} aria-label={label} aria-pressed={selected===b.key}><span>{tier}</span>{state.state!=="standing"&&<span className="building-status" aria-hidden="true">{state.state==="destroyed" ? "×" : "?"}</span>}</button>;
        })}
        {!failed && visibleWards.map(w=>{
          const pos=worldToPercent(w.x,w.y);
          const label=`${w.kind==="observer" ? "Observer" : "Sentry"} · ${w.side==="radiant" ? "Radiant" : "Dire"} · активен · установлен ${gameTimeLabel(w.placedAt)}`;
          return <button type="button" key={w.id} className={`replay-ward ${w.side} ${w.kind}`} style={{left:`${pos.left}%`,top:`${pos.top}%`}} title={label} aria-label={label} aria-pressed={selected===w.id} onClick={()=>setSelected(w.id)}><WardGlyph kind={w.kind}/></button>;
        })}
        {!failed&&[...currentHeroes.values()].filter(p=>p.alive && time-p.time<=30 && (perspective==="all"||(p.playerSlot<128 ? "radiant" : "dire")===perspective)).map(p=>{const pos=worldToPercent(p.x,p.y);return <span key={p.playerSlot} className={`replay-hero ${p.playerSlot<128 ? "radiant" : "dire"}`} style={{left:`${pos.left}%`,top:`${pos.top}%`}} title={`Игрок ${p.playerSlot<128?p.playerSlot+1:p.playerSlot-122}; срез ${gameTimeLabel(p.time)}`}>{p.playerSlot<128?p.playerSlot+1:p.playerSlot-122}</span>;})}
        <span className="map-team-label radiant">RADIANT</span><span className="map-team-label dire">DIRE</span>
      </div>
    </div>
    <div className="replay-map-legend">
      <span className="ward-radiant"><WardGlyph kind="observer"/>Radiant</span><span className="ward-dire"><WardGlyph kind="observer"/>Dire</span>
      <span><WardGlyph kind="sentry"/>Sentry</span><span>× Разрушена</span><span>? Состояние неизвестно</span>
      {camps&&<>{(["small","medium","large","ancient"] as const).map(tier=><span key={tier}><CampGlyph tier={tier}/>{CAMP_LABELS[tier]}</span>)}</>}
    </div>
    <div className="replay-map-detail" role="status">
      {building && buildingState ? <p><strong>{building.side==="radiant" ? "Radiant" : "Dire"} · {building.label}</strong> — {buildingState.state==="destroyed" ? `разрушена в ${gameTimeLabel(buildingState.destroyedAt!)}` : buildingState.state==="standing" ? "на выбранный момент стоит" : "в доступном журнале нет полного состояния этой постройки"}.</p>
        : ward ? <p><strong>{ward.kind==="observer" ? "Observer Ward" : "Sentry Ward"}</strong> · поставлен {gameTimeLabel(ward.placedAt)}. Действует на выбранной секунде.</p>
        : camp ? <p><strong>{CAMP_LABELS[camp.tier]}</strong> · сторона {camp.side==="radiant" ? "Radiant" : "Dire"}. Метка обозначает место лагеря; наличие крипов в этот момент неизвестно.</p>
        : <p>Выберите метку на карте.</p>}
      {wards&&!data.wardLifetimesComplete&&<p className="fine-print">Варды без подтверждённого времени снятия скрыты.</p>}
      <p className="map-image-credit">Карта: <a href="https://liquipedia.net/commons/File:Game_map_7.41.jpg" target="_blank" rel="noreferrer">Buny154 / Liquipedia</a> · © Valve Corporation</p>
      <p className="fine-print">Карта 7.41. Варды исчезают в момент снятия или окончания действия. Метки лагерей не показывают наличие крипов.</p>
    </div>
  </div>;
}
