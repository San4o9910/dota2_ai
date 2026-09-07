"use client";
import Link from "next/link";
import {useCallback,useEffect,useRef,useState} from "react";

type Video={id:string;filename:string;size_bytes:number;state:string;nickname:string;frame_count:number|null;processed_frames:number;failure_code:string|null};
type Batch={first_frame:number;last_frame:number;payload:{focus_player_visible:boolean;frames:Array<{frame_id:number;video_seconds:number}>;findings:Array<{frame_id:number;observation:string;advice:string;confidence:string}>}};
type Detail={video:Video;parts:number[];batches:Batch[];next_cursor:number|null};
const labels:Record<string,string>={uploading:"Загружается",queued:"В очереди",processing:"Разбираем кадры",ready:"Кадры обработаны",failed:"Обработка остановлена"};
const failures:Record<string,string>={VIDEO_FRAME_BUDGET_EXCEEDED:"В записи больше кадров, чем допускает тестовый режим. Обрежьте нужный эпизод и загрузите его заново.",VIDEO_GLOBAL_BUDGET_EXCEEDED:"Тестовый бюджет закончился. Уже обработанные кадры сохранены.",VIDEO_GLOBAL_BUDGET_DISABLED:"Видеоанализ приостановлен. Сохранённые результаты доступны.",VIDEO_REQUEST_BUDGET_EXCEEDED:"Достигнут лимит запросов. Обработанные кадры сохранены.",VIDEO_BUDGET_RECONCILIATION_REQUIRED:"Расходы Gemini требуют проверки. Новые запросы остановлены.",GEMINI_PLAYER_UNCONFIRMED:"Не удалось уверенно определить закреплённого игрока в кадре."};
const stamp=(seconds:number)=>`${Math.floor(seconds/60)}:${Math.floor(seconds%60).toString().padStart(2,"0")}.${Math.floor(seconds%1*1000).toString().padStart(3,"0")}`;
async function api<T>(url:string,options?:RequestInit):Promise<T>{const response=await fetch(url,{...options,credentials:"same-origin",cache:"no-store"});const data=await response.json() as {error?:unknown};if(!response.ok)throw new Error(typeof data.error==="string"?data.error:"Не удалось выполнить запрос.");return data as T;}
export default function VideoWorkspace(){
  const [videos,setVideos]=useState<Video[]>([]),[configured,setConfigured]=useState(false),[workerReady,setWorkerReady]=useState(false);
  const [frameBudget,setFrameBudget]=useState(3600),[budgetAvailable,setBudgetAvailable]=useState(false);
  const [profile,setProfile]=useState<{nickname:string}|null>(null),[profileLoaded,setProfileLoaded]=useState(false);
  const [file,setFile]=useState<File|null>(null),[busy,setBusy]=useState(false),[percent,setPercent]=useState(0),[message,setMessage]=useState("");
  const [selected,setSelected]=useState<Detail|null>(null);const video=useRef<HTMLVideoElement>(null),uploadId=useRef<string|null>(null),selectedId=useRef<string|null>(null);
  const load=useCallback(async()=>{const data=await api<{videos:Video[];configured?:boolean;worker_ready:boolean;frame_budget?:number;budget_available?:boolean}>("/api/videos");setVideos(data.videos);setConfigured(data.configured!==false);setWorkerReady(data.worker_ready);setFrameBudget(data.frame_budget??3600);setBudgetAvailable(data.budget_available===true);},[]);
  useEffect(()=>{const refresh=()=>void load().catch(error=>setMessage(error.message));const first=setTimeout(refresh,0);const timer=setInterval(refresh,10000);return()=>{clearTimeout(first);clearInterval(timer);};},[load]);
  useEffect(()=>{let active=true;void api<{profile:{nickname:string}|null}>("/api/account/dota-player").then(data=>{if(active){setProfile(data.profile);setProfileLoaded(true);}}).catch(error=>{if(active)setMessage(error.message);});return()=>{active=false;};},[]);
  const activeVideoId=selected?.video.id,activeVideoState=selected?.video.state;
  useEffect(()=>{if(!activeVideoId||!["queued","processing"].includes(activeVideoState??""))return;const id=activeVideoId;const timer=setInterval(()=>{void api<Detail>(`/api/videos/${id}`).then(next=>{if(selectedId.current===id)setSelected(next);}).catch(()=>{});},10000);return()=>clearInterval(timer);},[activeVideoId,activeVideoState]);
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
    <section className="surface replay-upload-panel"><h1>Разбор видео</h1><p>Выберите эпизод, который хотите проверить: выход на линию, драку или смерть.</p><p className="field-help">Обрабатываем каждый кадр по порядку. В полном матче сначала нужно выбрать и вырезать нужный фрагмент.</p>
      {profile?<p>Игрок: <strong>{profile.nickname}</strong></p>:profileLoaded&&<p className="analysis-notice">Сначала <Link href="/replays">загрузите свой .dem и закрепите ник</Link>. Для этого OpenDota не нужна.</p>}
      <p className="field-help">Видео само по себе не подтверждает Steam-аккаунт. Если игрока нельзя уверенно узнать в кадре, персонального вывода не будет.</p>
      <label htmlFor="video-upload">Видео матча</label><input id="video-upload" type="file" accept=".mp4,.mkv,.webm,.mov" disabled={busy||!configured} onChange={event=>{setFile(event.target.files?.[0]??null);uploadId.current=null;setPercent(0);}}/>
      <p className="field-help">Тестовый предел — {frameBudget.toLocaleString("ru-RU")} кадров: до {Math.floor(frameBudget/30)} секунд при 30 FPS или {Math.floor(frameBudget/60)} секунд при 60 FPS. MP4, MKV, WebM или MOV, до 2 ГБ. Сохраняйте читаемые миникарту, предметы и способности.</p>
      <button type="button" disabled={!file||busy||!configured||!profile||!budgetAvailable} onClick={()=>void upload()}>{busy?`Загружаем · ${percent}%`:percent>0?"Продолжить загрузку":"Загрузить и разобрать"}</button>
      {busy&&<progress value={percent} max={100} aria-label="Загрузка видео"/>}
      {!configured?<p className="analysis-notice">Видеоанализ ещё не подключён к этой версии платформы.</p>:!workerReady&&<p className="analysis-notice">Обработчик сейчас не запущен. Видео сохранится в очереди.</p>}
      {configured&&!budgetAvailable&&<p className="analysis-notice">Тестовый бюджет исчерпан или приостановлен. Сохранённые результаты можно открыть ниже.</p>}
      <p role="status">{message}</p>
    </section>
    <section className="surface replay-upload-panel"><h2>Мои видео</h2>{!videos.length&&<p>Здесь появятся ваши записи и результаты.</p>}
      {videos.map(item=><article className="replay-upload-row" key={item.id}><div><strong>{item.filename}</strong><p>{labels[item.state]??item.state} · {item.nickname}</p>{item.frame_count!==null&&<p>{item.processed_frames.toLocaleString("ru-RU")} / {item.frame_count.toLocaleString("ru-RU")} кадров</p>}{item.state==="failed"&&<p>Частичные результаты сохранены. Полное покрытие кадров не подтверждено.</p>}</div><button type="button" onClick={()=>void open(item.id)}>Открыть</button><button type="button" disabled={busy} onClick={()=>void remove(item.id)}>Удалить</button></article>)}
    </section>
    {selected&&<section className="surface replay-upload-panel video-results"><div className="analysis-section-title"><h2>{selected.video.filename}</h2><button type="button" onClick={()=>void open(selected.video.id)}>Обновить результат</button></div>
      {selected.video.state!=="uploading"&&<video key={selected.video.id} ref={video} controls playsInline preload="metadata" src={`/api/videos/${selected.video.id}/source`}/>}
      <p>Таймкоды относятся к записи. Выводы основаны на видимом в кадре; события вне камеры требуют проверки по реплею.</p>
      {selected.video.state==="failed"&&<p role="status" className="analysis-notice">{failures[selected.video.failure_code??""]??"Не удалось завершить обработку. Частичные результаты сохранены."}</p>}
      {selected.batches.flatMap(batch=>batch.payload.findings.map((finding,index)=>{const frame=batch.payload.frames.find(item=>item.frame_id===finding.frame_id);return <article className="video-finding" key={`${batch.first_frame}-${index}`}><button type="button" onClick={()=>{if(video.current&&frame)video.current.currentTime=frame.video_seconds;}}>{frame?stamp(frame.video_seconds):`Кадр ${finding.frame_id}`}</button><p>{finding.observation}</p>{finding.advice&&<p>{finding.advice}</p>}{finding.confidence!=="high"&&<small>Требует проверки</small>}</article>;}))}
      {!selected.batches.length&&<p>Наблюдения появятся после обработки первых кадров.</p>}
      {selected.batches.length>0&&selected.batches.every(batch=>!batch.payload.findings.length)&&<p>В показанных кадрах нет подтверждённых наблюдений о закреплённом игроке.</p>}
      {selected.next_cursor!==null&&<button type="button" onClick={()=>void more()}>Следующие эпизоды</button>}
    </section>}
  </main>;
}
