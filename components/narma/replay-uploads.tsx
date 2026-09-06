"use client";
import Link from "next/link";
import {useCallback,useEffect,useRef,useState} from "react";
import MatchReplayPanel from "@/components/narma/match-replay-panel";
import {NormalizedMatchV1Schema,EvidenceBundleV1Schema} from "@/lib/analysis/contracts";
import type {AnalysisDetail} from "@/lib/analyses/contracts";
type Upload={id:string;filename:string;sizeBytes:number;state:string;matchId:string|null;createdAt:string};
const LABELS:Record<string,string>={uploading:"Загружается",uploaded:"Файл сохранён · ожидает обработчика",processing:"Разбираем реплей",ready:"Готов",failed:"Не удалось обработать"};
const PART=5*1024*1024;
export default function ReplayUploads(){
  const [uploads,setUploads]=useState<Upload[]>([]);const [enabled,setEnabled]=useState(false);const [file,setFile]=useState<File|null>(null);
  const [busy,setBusy]=useState(false);const [percent,setPercent]=useState(0);const [notice,setNotice]=useState("");const [detail,setDetail]=useState<AnalysisDetail|null>(null);const [time,setTime]=useState(0);
  const session=useRef<string|null>(null);const attempt=useRef<string|null>(null);
  const load=useCallback(async()=>{const response=await fetch("/api/replays");const body=await response.json() as {uploads?:Upload[];enabled?:boolean;error?:string};if(!response.ok)throw new Error(body.error);setUploads(body.uploads??[]);setEnabled(!!body.enabled);},[]);
  useEffect(()=>{const initial=setTimeout(()=>void load().catch(e=>setNotice(e.message)),0);const interval=setInterval(()=>void load().catch(()=>{}),10000);return()=>{clearTimeout(initial);clearInterval(interval);};},[load]);
  async function upload(){
    if(!file)return;setBusy(true);setNotice("");
    try{
      if(!session.current){attempt.current??=crypto.randomUUID();const response=await fetch("/api/replays",{method:"POST",headers:{"Content-Type":"application/json","Idempotency-Key":attempt.current},body:JSON.stringify({filename:file.name,sizeBytes:file.size})});const body=await response.json() as {id?:string;error?:string};if(!response.ok||!body.id)throw new Error(body.error);session.current=body.id;}
      const id=session.current;
      const statusResponse=await fetch(`/api/replays/${id}`);const status=await statusResponse.json() as {parts?:Array<{partNumber:number}>;error?:string};if(!statusResponse.ok)throw new Error(status.error);
      const done=new Set(status.parts?.map(p=>p.partNumber));
      for(let offset=0;offset<file.size;offset+=PART){const part=Math.floor(offset/PART)+1;
        if(!done.has(part)){const response=await fetch(`/api/replays/${id}?part=${part}`,{method:"PUT",headers:{"Content-Type":"application/octet-stream"},body:file.slice(offset,offset+PART)});if(!response.ok){const body=await response.json() as {error?:string};throw new Error(body.error);}}
        setPercent(Math.round(Math.min(file.size,offset+PART)/file.size*100));
      }
      const response=await fetch(`/api/replays/${id}`,{method:"POST"});if(!response.ok){const body=await response.json() as {error?:string};throw new Error(body.error);}
      session.current=null;attempt.current=null;setFile(null);setNotice("Реплей сохранён. Статус обработки появится в списке.");await load();
    }catch(e){setNotice(e instanceof Error ? e.message : "Загрузка прервалась. Повторите: уже переданные части сохранены.");}finally{setBusy(false);}
  }
  async function remove(id:string){try{const response=await fetch(`/api/replays/${id}`,{method:"DELETE"});if(!response.ok){const body=await response.json() as {error?:string};throw new Error(body.error);}if(session.current===id)session.current=null;await load();}catch(e){setNotice(e instanceof Error ? e.message : "Не удалось удалить реплей.");}}
  async function open(upload:Upload){try{const response=await fetch(`/api/replays/${upload.id}`);const body=await response.json() as {match?:unknown;evidenceBundle?:unknown;error?:string};if(!response.ok)throw new Error(body.error);const match=NormalizedMatchV1Schema.parse(body.match);const evidenceBundle=EvidenceBundleV1Schema.parse(body.evidenceBundle);setTime(0);setDetail({job:{id:upload.id,matchId:match.matchId,playerSlot:0,reportVersion:"analysis-report.v1",state:"ready",attempt:1,maxAttempts:3,failure:null,createdAt:upload.createdAt,updatedAt:upload.createdAt},report:null,match,evidenceBundle});}catch(e){setNotice(e instanceof Error?e.message:"Не удалось открыть реплей.");}}
  return <main className="analysis-workspace" id="main-content"><header className="analysis-workspace-header"><Link className="brand" href="/">NARMA VISION</Link><Link href="/analyses">Разборы</Link><Link href="/account">Аккаунт</Link></header>
    <section className="surface replay-upload-panel"><h1>Загрузить реплей</h1><p>Выберите <strong>.dem</strong> или <strong>.dem.bz2</strong> до 512 МБ. Файл и разбор доступны вашему аккаунту.</p>
      <p className="fine-print">В Dota 2 скачайте повтор матча. На компьютере файл находится в папке игры: game/dota/replays.</p>
      <label htmlFor="dem-upload">Файл реплея</label><input id="dem-upload" type="file" accept=".dem,.bz2" disabled={busy||!enabled} onChange={e=>{session.current=null;attempt.current=null;setPercent(0);setFile(e.target.files?.[0]??null);}}/>
      {file&&<p>{file.name} · {(file.size/1024/1024).toFixed(1)} МБ</p>}
      <button type="button" disabled={!file||busy||!enabled} onClick={()=>void upload()}>{busy ? `Загружаем · ${percent}%` : percent>0 ? "Продолжить загрузку" : "Загрузить"}</button>
      {busy&&<progress value={percent} max={100} aria-label="Загрузка реплея"/>}
      {!enabled&&<p>Хранилище реплеев пока не подключено к этой версии сайта.</p>}
      <p role="status">{notice}</p>
    </section>
    <section className="surface replay-upload-panel"><h2>Ваши реплеи</h2>{uploads.length===0&&<p>Здесь появятся загруженные файлы.</p>}{uploads.map(item=><article key={item.id} className="replay-upload-row"><div><strong>{item.filename}</strong><p>{LABELS[item.state]??item.state} · {(item.sizeBytes/1024/1024).toFixed(1)} МБ</p></div>{["uploaded","processing","ready","failed"].includes(item.state)&&item.filename.endsWith(".dem")&&<Link href={`/analyses?replay=${item.id}${item.matchId?`&match=${item.matchId}`:""}`}>Закрепить мой ник</Link>}{item.state==="ready"&&<button type="button" onClick={()=>void open(item)}>Открыть карту</button>}<button type="button" disabled={busy} onClick={()=>void remove(item.id)}>Удалить</button></article>)}</section>
    {detail&&<section className="surface replay-upload-panel"><MatchReplayPanel detail={detail} time={time} onSeek={setTime}/><Link href={`/analyses?match=${detail.job.matchId}`}>Разобрать мой матч</Link></section>}
  </main>;
}
