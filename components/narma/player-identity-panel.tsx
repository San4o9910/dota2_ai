"use client";
import { useEffect, useId, useState, useRef } from "react";
import heroCatalog from "@/app/data/hero-catalog.json";
import type { DotaProfile } from "@/lib/dota/player-binding";
import type { PlayerTarget } from "@/lib/dota/player-identity";

export default function PlayerIdentityPanel({matchId,onResolved,onBusyChange}:{matchId:string;onResolved?:(target:PlayerTarget)=>void;onBusyChange?:(busy:boolean)=>void}) {
  const id=useId();
  const bindingStarted=useRef(false);
  const [profile,setProfile]=useState<DotaProfile|null>(null);
  const [nickname,setNickname]=useState("");
  const [target,setTarget]=useState<PlayerTarget|null>(null);
  const [pending,setPending]=useState(false);
  const [message,setMessage]=useState("");
  useEffect(()=>{
    const controller=new AbortController();
    fetch("/api/account/dota-player",{credentials:"same-origin",cache:"no-store",signal:controller.signal})
      .then(async response=>{if(response.ok){const data=await response.json() as {profile?:DotaProfile|null};if(!bindingStarted.current)setProfile(data.profile??null);}})
      .catch(()=>{});
    return()=>controller.abort();
  },[]);
  const resolve=async()=>{
    bindingStarted.current=true;setPending(true);onBusyChange?.(true);setMessage("");
    try {
      const response=await fetch("/api/account/dota-player",{method:"POST",credentials:"same-origin",cache:"no-store",headers:{"Content-Type":"application/json"},body:JSON.stringify({matchId,...(!profile?{nickname:nickname.trim()}: {})})});
      const data=await response.json() as {profile:DotaProfile;target:PlayerTarget;error?:string|{message?:string}};
      if(!response.ok)throw new Error(typeof data.error==="string"?data.error:data.error?.message??"Не удалось найти игрока.");
      setProfile(data.profile);setTarget(data.target);onResolved?.(data.target);
    } catch(error) {setMessage(error instanceof Error?error.message:"Не удалось найти игрока.");}
    finally{setPending(false);onBusyChange?.(false);}
  };
  const current=target?.matchId===matchId?target:null;
  const hero=current?(heroCatalog as Record<string,{name:string}>)[String(current.heroId)]?.name:null;
  return <div className="player-identity-panel">
    <label htmlFor={`${id}-nickname`}>Ник в Dota 2</label>
    <input id={`${id}-nickname`} name="nickname" type="text" value={profile?.nickname??nickname} readOnly={!!profile} disabled={pending} maxLength={128} autoComplete="off" placeholder="Ваш игровой ник" aria-describedby={`${id}-help`} onChange={event=>{setNickname(event.target.value);setMessage("");}}/>
    <p className="field-help" id={`${id}-help`}>{profile?"Игрок закреплён за аккаунтом. Смена ника в Dota не меняет привязку.":"Укажите ник из этого матча. Первый поиск закрепит одного игрока за аккаунтом."}</p>
    <button type="button" className="price-button secondary" disabled={pending||!/^[1-9]\d{7,11}$/.test(matchId)||(!profile&&!nickname.trim())} onClick={()=>void resolve()}>{pending?"Ищем игрока…":profile?"Найти меня в матче":"Найти и закрепить игрока"}</button>
    {current&&<p className="player-identity-result" role="status"><strong>{profile?.nickname}</strong> · {hero??"Герой найден"} · {current.playerSlot<128?"Radiant":"Dire"}<br/><small>Персональный разбор будет только для этого игрока.</small></p>}
    {message&&<p className="analysis-notice" role="alert">{message}</p>}
  </div>;
}
