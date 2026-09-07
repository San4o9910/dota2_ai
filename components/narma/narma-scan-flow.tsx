"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import PlayerIdentityPanel from "@/components/narma/player-identity-panel";
import type { PlayerTarget } from "@/lib/dota/player-identity";
import {formatScanMetricValue,formatScanTime,isJsonResponseMediaType,parseScanSuccess,scanKindLabel,scanMetricLabel,scanSideLabel,type ScanPreview} from "@/components/narma/scan-presentation";
const MAX_RESPONSE_CHARACTERS=64*1024;
class ScanUiError extends Error {}
async function readBoundedJson(response: Response): Promise<unknown> {
  const declaredLength = Number(response.headers.get("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > MAX_RESPONSE_CHARACTERS) {
    throw new ScanUiError("Сервер вернул слишком большой ответ.");
  }
  if (!isJsonResponseMediaType(response.headers.get("content-type"))) {
    throw new ScanUiError("Сервер вернул ответ в неожиданном формате.");
  }
  let text = "";
  if (!response.body) {
    text = await response.text();
    if (text.length > MAX_RESPONSE_CHARACTERS) {
      throw new ScanUiError("Сервер вернул слишком большой ответ.");
    }
  } else {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let receivedBytes = 0;
    try {
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        receivedBytes += chunk.value.byteLength;
        if (receivedBytes > MAX_RESPONSE_CHARACTERS) {
          await reader.cancel();
          throw new ScanUiError("Сервер вернул слишком большой ответ.");
        }
        text += decoder.decode(chunk.value, { stream: true });
      }
      text += decoder.decode();
    } finally {
      reader.releaseLock();
    }
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new ScanUiError("Сервер вернул повреждённый ответ.");
  }
}

export default function NarmaScanFlow() {
  const [matchId,setMatchId]=useState("");
  const [target,setTarget]=useState<PlayerTarget|null>(null);
  const [preview,setPreview]=useState<ScanPreview|null>(null);
  const [pending,setPending]=useState(false);
  const [bindingBusy,setBindingBusy]=useState(false);
  const [message,setMessage]=useState("");
  const controller=useRef<AbortController|null>(null);
  const requestNumber=useRef(0);
  useEffect(()=>()=>{requestNumber.current++;controller.current?.abort();},[]);
  const cancel=()=>{requestNumber.current++;controller.current?.abort();setPending(false);setMessage("Загрузка отменена.");};
  const scan=async(event:React.FormEvent)=>{
    event.preventDefault();
    if(!target||target.matchId!==matchId)return;
    controller.current?.abort();controller.current=new AbortController();
    const sequence=++requestNumber.current;
    setPending(true);setMessage("");setPreview(null);
    try {
      const response=await fetch("/api/scan",{method:"POST",credentials:"same-origin",cache:"no-store",headers:{"Content-Type":"application/json"},body:JSON.stringify({matchId}),signal:controller.current.signal});
      const payload=await readBoundedJson(response);
      if(sequence!==requestNumber.current)return;
      if(!response.ok){const error=(payload as {error?:string|{message?:string}})?.error;throw new Error(typeof error==="string"?error:error?.message??"Не удалось получить данные матча.");}
      const result=parseScanSuccess(payload);
      if(!result||result.status!=="ready"||result.preview.matchId!==matchId||result.preview.playerSlot!==target.playerSlot)throw new Error("Ответ не соответствует закреплённому игроку.");
      setPreview(result.preview);
    } catch(error){if(sequence===requestNumber.current)setMessage(error instanceof Error?error.message:"Не удалось загрузить матч.");}
    finally{if(sequence===requestNumber.current)setPending(false);}
  };
  return <div className="scan-flow">
    <h2 id="match-dialog-title">Мой матч</h2>
    <p id="match-dialog-description">Укажите матч и свой ник. Персональный разбор закрепляется за одним игроком.</p>
    <form onSubmit={scan} noValidate aria-busy={pending||bindingBusy}>
      <label htmlFor="scan-match-id">Match ID</label>
      <input id="scan-match-id" disabled={bindingBusy} data-dialog-initial-focus name="matchId" inputMode="numeric" maxLength={12} autoComplete="off" value={matchId} placeholder="8963624400" onChange={event=>{cancel();setMessage("");setMatchId(event.target.value.replace(/\D/g,"").slice(0,12));setTarget(null);setPreview(null);}}/>
      <PlayerIdentityPanel matchId={matchId} onResolved={setTarget} onBusyChange={setBindingBusy}/>
      <button className="dialog-submit" type="submit" disabled={pending||!target||target.matchId!==matchId}>{pending?"Загружаем факт…":"Показать мой эпизод"}</button>
      {pending&&<button className="dialog-secondary" type="button" onClick={cancel}>Отменить загрузку</button>}
    </form>
    <p role="status" aria-live="polite" aria-atomic="true">{message|| (pending ? "Загружаем эпизод…":"")}</p>
    {preview&&<section className="scan-preview" aria-live="polite">
      <h3>Один факт из матча</h3>
      <div className="scan-preview-lead"><span>{scanKindLabel(preview.kind)}</span><strong>{formatScanTime(preview.atSeconds)}</strong><small>{scanSideLabel(preview.team)}</small></div>
      <dl className="scan-metrics">{preview.metrics.map(metric=><div key={`${metric.metric}-${metric.unit}`}><dt>{scanMetricLabel(metric.metric)}</dt><dd>{formatScanMetricValue(metric)}</dd></div>)}</dl>
      <p>Это наблюдение по доступным данным, а не установленная причина поражения.</p>
      <Link className="price-button" href={`/analyses?matchId=${matchId}`}>Мой полный разбор</Link>
    </section>}
  </div>;
}
