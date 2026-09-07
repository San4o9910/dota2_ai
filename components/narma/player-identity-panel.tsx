"use client";
import { useEffect, useId, useState, useRef } from "react";
import heroCatalog from "@/app/data/hero-catalog.json";
import type { DotaProfile } from "@/lib/dota/player-binding";
import type { PlayerTarget } from "@/lib/dota/player-identity";
import Link from "next/link";
type ReplayOption={id:string;filename:string;state:string};

export default function PlayerIdentityPanel({matchId,initialReplayId="",onResolved,onBusyChange}:{matchId:string;initialReplayId?:string;onResolved?:(target:PlayerTarget)=>void;onBusyChange?:(busy:boolean)=>void}) {
  const id=useId();
  const bindingStarted=useRef(false);
  const [profile,setProfile]=useState<DotaProfile|null>(null);
  const [nickname,setNickname]=useState("");
  const [target,setTarget]=useState<PlayerTarget|null>(null);
  const [pending,setPending]=useState(false);
  const [message,setMessage]=useState("");
  const [replays,setReplays]=useState<ReplayOption[]>([]);
  const [replayId,setReplayId]=useState(initialReplayId);
  const [awaitingMatch,setAwaitingMatch]=useState<string|null>(null);
  useEffect(()=>{
    const controller=new AbortController();
    fetch("/api/account/dota-player",{credentials:"same-origin",cache:"no-store",signal:controller.signal})
      .then(async response=>{if(response.ok){const data=await response.json() as {profile?:DotaProfile|null};if(!bindingStarted.current)setProfile(data.profile??null);}})
      .catch(()=>{});
    fetch("/api/replays",{credentials:"same-origin",cache:"no-store",signal:controller.signal})
      .then(async response=>{if(response.ok){const data=await response.json() as {uploads?:ReplayOption[]};setReplays((data.uploads??[]).filter(replay=>["uploaded","processing","ready","failed"].includes(replay.state)&&replay.filename.endsWith(".dem")));}})
      .catch(()=>{});
    return()=>controller.abort();
  },[]);
  const resolve=async()=>{
    bindingStarted.current=true;setPending(true);onBusyChange?.(true);setMessage("");setAwaitingMatch(null);
    try {
      const response=await fetch("/api/account/dota-player",{method:"POST",credentials:"same-origin",cache:"no-store",headers:{"Content-Type":"application/json"},body:JSON.stringify({matchId,...(replayId?{replayId}:{}),...(!profile?{nickname:nickname.trim()}: {})})});
      const data=await response.json() as {profile:DotaProfile;target:PlayerTarget|null;status?:string;error?:string|{message?:string}};
      if(!response.ok)throw new Error(typeof data.error==="string"?data.error:data.error?.message??"Не удалось найти игрока.");
      setProfile(data.profile);setTarget(data.target);
      if(data.target)onResolved?.(data.target);else setAwaitingMatch(matchId);
    } catch(error) {setMessage(error instanceof Error?error.message:"Не удалось найти игрока.");}
    finally{setPending(false);onBusyChange?.(false);}
  };
  const current=target?.matchId===matchId?target:null;
  const hero=current?(heroCatalog as Record<string,{name:string}>)[String(current.heroId)]?.name:null;
  return <div className="player-identity-panel">
    <label htmlFor={`${id}-nickname`}>Ник в Dota 2</label>
    <input id={`${id}-nickname`} name="nickname" type="text" value={profile?.nickname??nickname} readOnly={!!profile} disabled={pending} maxLength={128} autoComplete="off" placeholder="Ваш игровой ник" aria-describedby={`${id}-help`} onChange={event=>{setNickname(event.target.value);setMessage("");}}/>
    <p className="field-help" id={`${id}-help`}>{profile?"Игрок закреплён за аккаунтом. Смена ника в Dota не меняет привязку.":"Укажите ник из этого матча. Первый поиск закрепит одного игрока за аккаунтом."}</p>
    <label htmlFor={`${id}-source`}>Источник состава игроков</label>
    <select id={`${id}-source`} value={replayId} disabled={pending} onChange={event=>{setReplayId(event.target.value);setMessage("");}}>
      <option value="">OpenDota · по Match ID</option>
      {replayId&&!replays.some(replay=>replay.id===replayId)&&<option value={replayId}>Выбранный реплей</option>}
      {replays.map(replay=><option key={replay.id} value={replay.id}>{replay.filename}</option>)}
    </select>
    <p className="field-help"><Link href="/replays">Загрузить .dem</Link> — из него можно закрепить ник без OpenDota.</p>
    <button type="button" className="price-button secondary" disabled={pending||!/^[1-9]\d{7,11}$/.test(matchId)||(!profile&&!nickname.trim())} onClick={()=>void resolve()}>{pending?"Ищем игрока…":profile?"Найти меня в матче":"Найти и закрепить игрока"}</button>
    {current&&<p className="player-identity-result" role="status"><strong>{profile?.nickname}</strong> · {hero??"Герой найден"} · {current.playerSlot<128?"Radiant":"Dire"}<br/><small>Персональный разбор будет только для этого игрока.</small></p>}
    {awaitingMatch===matchId&&<p className="player-identity-result" role="status"><strong>{profile?.nickname} закреплён по реплею.</strong><br/>Для создания разбора ещё требуется обработка файла.</p>}
    {message&&<p className="analysis-notice" role="alert">{message}</p>}
  </div>;
}
