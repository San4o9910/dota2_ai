"use client";
import Link from "next/link";
import {useCallback,useEffect,useRef,useState} from "react";

type Video={id:string;filename:string;size_bytes:number;state:string;nickname:string;frame_count:number|null;processed_frames:number;failure_code:string|null};
type Batch={first_frame:number;last_frame:number;payload:{focus_player_visible:boolean;frames:Array<{frame_id:number;video_seconds:number}>;findings:Array<{frame_id:number;observation:string;advice:string;confidence:string}>}};
type Detail={video:Video;parts:number[];batches:Batch[];next_cursor:number|null};
const labels:Record<string,string>={uploading:"Загружается",queued:"В очереди",processing:"Разбираем кадры",ready:"Кадры обработаны",failed:"Обработка остановлена"};
const stamp=(seconds:number)=>`${Math.floor(seconds/60)}:${Math.floor(seconds%60).toString().padStart(2,"0")}.${Math.floor(seconds%1*1000).toString().padStart(3,"0")}`;
async function api<T>(url:string,options?:RequestInit):Promise<T>{const response=await fetch(url,{...options,credentials:"same-origin",cache:"no-store"});const data=await response.json() as {error?:unknown};if(!response.ok)throw new Error(typeof data.error==="string"?data.error:"Не удалось выполнить запрос.");return data as T;}
export default function VideoWorkspace(){
  const [videos,setVideos]=useState<Video[]>([]),[configured,setConfigured]=useState(false),[workerReady,setWorkerReady]=useState(false);
  const [file,setFile]=useState<File|null>(null),[busy,setBusy]=useState(false),[percent,setPercent]=useState(0),[message,setMessage]=useState("");
  const [selected,setSelected]=useState<Detail|null>(null);const video=useRef<HTMLVideoElement>(null),uploadId=useRef<string|null>(null),selectedId=useRef<string|null>(null);
  const load=useCallback(async()=>{const data=await api<{videos:Video[];configured?:boolean;worker_ready:boolean}>("/api/videos");setVideos(data.videos);setConfigured(data.configured!==false);setWorkerReady(data.worker_ready);},[]);
  useEffect(()=>{const refresh=()=>void load().catch(error=>setMessage(error.message));const first=setTimeout(refresh,0);const timer=setInterval(refresh,10000);return()=>{clearTimeout(first);clearInterval(timer);};},[load]);
  const open=async(id:string)=>{selectedId.current=id;try{const result=await api<Detail>(`/api/videos/${id}`);if(selectedId.current===id)setSelected(result);}catch(error){setMessage((error as Error).message);}};
  async function upload(){if(!file)return;setBusy(true);setMessage("");try{
    uploadId.current??=crypto.randomUUID();const id=uploadId.current;
    const init=await api<{part_bytes:number;video:Video}>("/api/videos",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id,filename:file.name,size_bytes:file.size})});
    if(init.video.state==="uploading"){
      const status=await api<Detail>(`/api/videos/${id}`),done=new Set(status.parts);
      for(let offset=0;offset<file.size;offset+=init.part_bytes){const part=Math.floor(offset/init.part_bytes)+1;
        if(!done.has(part))await api(`/api/videos/${id}?part=${part}`,{method:"PUT",headers:{"Content-Type":"application/octet-stream"},body:file.slice(offset,offset+init.part_bytes)});
        setPercent(Math.round(Math.min(file.size,offset+init.part_bytes)/file.size*100));
      }
      await api(`/api/videos/${id}`,{method:"POST"});
    }
    uploadId.current=null;setFile(null);setMessage("Видео добавлено в очередь. Можно закрыть страницу — обработка продолжится на сервере.");await load();await open(id);
  }catch(error){setMessage((error as Error).message);}finally{setBusy(false);}}
  async function more(){if(!selected||selected.next_cursor===null)return;const id=selected.video.id;try{const next=await api<Detail>(`/api/videos/${id}?after=${selected.next_cursor}`);if(selectedId.current===id)setSelected({...next,batches:[...selected.batches,...next.batches]});}catch(error){setMessage((error as Error).message);}}
  async function remove(id:string){try{await api(`/api/videos/${id}`,{method:"DELETE"});if(selectedId.current===id){selectedId.current=null;setSelected(null);}await load();}catch(error){setMessage((error as Error).message);}}
  return <main className="analysis-workspace" id="main-content">
    <header className="analysis-workspace-header"><Link className="brand" href="/">NARMA VISION</Link><Link href="/analyses">Разборы матчей</Link><Link href="/account">Аккаунт</Link></header>
    <section className="surface replay-upload-panel"><h1>Разбор видео</h1><p>Загрузите запись игры. Для поиска игрока используем ник из вашего профиля.</p><p className="field-help">Видео само по себе не подтверждает Steam-аккаунт. Если игрока нельзя уверенно узнать в кадре, персонального вывода не будет.</p>
      <label htmlFor="video-upload">Видео матча</label><input id="video-upload" type="file" accept=".mp4,.mkv,.webm,.mov" disabled={busy||!configured} onChange={event=>{setFile(event.target.files?.[0]??null);uploadId.current=null;setPercent(0);}}/>
      <p className="field-help">MP4, MKV, WebM или MOV, до 2 ГБ. Сохраняйте читаемые миникарту, предметы и способности.</p>
      <button type="button" disabled={!file||busy||!configured} onClick={()=>void upload()}>{busy?`Загружаем · ${percent}%`:percent>0?"Продолжить загрузку":"Загрузить и разобрать"}</button>
      {busy&&<progress value={percent} max={100} aria-label="Загрузка видео"/>}
      {!configured?<p className="analysis-notice">Видеоанализ ещё не подключён к этой версии платформы.</p>:!workerReady&&<p className="analysis-notice">Обработчик сейчас не запущен. Видео сохранится в очереди.</p>}
      <p role="status">{message}</p><Link href="/analyses">Закрепить свой профиль Dota</Link>
    </section>
    <section className="surface replay-upload-panel"><h2>Мои видео</h2>{!videos.length&&<p>Здесь появятся ваши записи и результаты.</p>}
      {videos.map(item=><article className="replay-upload-row" key={item.id}><div><strong>{item.filename}</strong><p>{labels[item.state]??item.state} · {item.nickname}</p>{item.frame_count!==null&&<p>{item.processed_frames.toLocaleString("ru-RU")} / {item.frame_count.toLocaleString("ru-RU")} кадров</p>}{item.state==="failed"&&<p>Частичные результаты сохранены. Полное покрытие кадров не подтверждено.</p>}</div><button type="button" onClick={()=>void open(item.id)}>Открыть</button><button type="button" disabled={busy} onClick={()=>void remove(item.id)}>Удалить</button></article>)}
    </section>
    {selected&&<section className="surface replay-upload-panel video-results"><div className="analysis-section-title"><h2>{selected.video.filename}</h2><button type="button" onClick={()=>void open(selected.video.id)}>Обновить результат</button></div>
      {selected.video.state!=="uploading"&&<video key={selected.video.id} ref={video} controls playsInline preload="metadata" src={`/api/videos/${selected.video.id}/source`}/>}
      <p>Таймкоды относятся к записи. Выводы основаны на видимом в кадре; события вне камеры требуют проверки по реплею.</p>
      {selected.batches.flatMap(batch=>batch.payload.findings.map((finding,index)=>{const frame=batch.payload.frames.find(item=>item.frame_id===finding.frame_id);return <article className="video-finding" key={`${batch.first_frame}-${index}`}><button type="button" onClick={()=>{if(video.current&&frame)video.current.currentTime=frame.video_seconds;}}>{frame?stamp(frame.video_seconds):`Кадр ${finding.frame_id}`}</button><p>{finding.observation}</p>{finding.advice&&<p>{finding.advice}</p>}{finding.confidence!=="high"&&<small>Требует проверки</small>}</article>;}))}
      {!selected.batches.length&&<p>Наблюдения появятся после обработки первых кадров.</p>}
      {selected.batches.length>0&&selected.batches.every(batch=>!batch.payload.findings.length)&&<p>В показанных кадрах нет подтверждённых наблюдений о закреплённом игроке.</p>}
      {selected.next_cursor!==null&&<button type="button" onClick={()=>void more()}>Следующие эпизоды</button>}
    </section>}
  </main>;
}
