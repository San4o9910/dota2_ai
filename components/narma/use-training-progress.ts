"use client";
import {useCallback,useEffect,useRef,useState} from "react";

export function useTrainingProgress(contextId:string,enabled=true) {
  const [completed,setCompleted]=useState<Record<string,boolean>>({});
  const [status,setStatus]=useState("");
  const [saving,setSaving]=useState(false);
  const busy=useRef(false);
  useEffect(()=>{
    const controller=new AbortController();
    if(!enabled) return;
    fetch(`/api/training?context=${encodeURIComponent(contextId)}`,{signal:controller.signal}).then(async response=>{
      const body=await response.json() as {error?:string;progress:Array<{taskId:string;completed:number}>};if(!response.ok) throw new Error(body.error);
      setCompleted(Object.fromEntries(body.progress.map((p:{taskId:string;completed:number})=>[p.taskId,!!p.completed])));
      setStatus("Прогресс сохранён в аккаунте");
    }).catch(error=>{if(!controller.signal.aborted)setStatus(error.message || "Не удалось загрузить прогресс");});
    return ()=>controller.abort();
  },[contextId,enabled]);
  const toggle=useCallback(async(taskId:string,value:boolean)=>{
    if(!enabled){setStatus("Войдите, чтобы сохранять упражнения.");return;}
    if(busy.current) return;busy.current=true;setSaving(true);setStatus("Сохраняем…");
    try {
      const response=await fetch("/api/training",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({contextId,taskId,completed:value})});
      const body=await response.json() as {error?:string;progress:Array<{taskId:string;completed:number}>};if(!response.ok) throw new Error(body.error);
      setCompleted(current=>({...current,[taskId]:value}));setStatus("Сохранено в аккаунте");
    }catch(error){setStatus(error instanceof Error ? error.message : "Не удалось сохранить. Попробуйте ещё раз.");}
    finally{busy.current=false;setSaving(false);}
  },[contextId,enabled]);
  return {completed,status,saving,toggle};
}
