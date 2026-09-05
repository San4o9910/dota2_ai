"use client";
import {useEffect,useState} from "react";
import {useTrainingProgress} from "@/components/narma/use-training-progress";
import type {AnalysisReportV1,EvidenceTimeV1} from "@/lib/analysis/contracts";
type Answer={text:string;evidenceIds:string[];time:EvidenceTimeV1};
export default function ReportFollowup({jobId,report,time,onSeek}:{jobId:string;report:AnalysisReportV1;time:number;onSeek:(t:number)=>void}) {
  const progress=useTrainingProgress(jobId);
  const [question,setQuestion]=useState("");
  const [answer,setAnswer]=useState<Answer|null>(null);
  const [notice,setNotice]=useState("");const [busy,setBusy]=useState(false);
  useEffect(()=>{const c=new AbortController();fetch(`/api/analyses/${jobId}/questions`,{signal:c.signal}).then(async r=>{const data=await r.json() as {exchanges?:Array<{answer:string}>};if(r.ok&&data.exchanges?.length)setAnswer(JSON.parse(data.exchanges.at(-1)!.answer));}).catch(()=>{});return()=>c.abort();},[jobId]);
  async function ask(){setBusy(true);setNotice("");try{const response=await fetch(`/api/analyses/${jobId}/questions`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:crypto.randomUUID(),question,time})});const data=await response.json() as {answer?:Answer;error?:string};if(!response.ok||!data.answer)throw new Error(data.error);setAnswer(data.answer);setQuestion("");}catch(e){setNotice(e instanceof Error ? e.message : "Не удалось получить ответ.");}finally{setBusy(false);}}
  return <section className="report-followup">
    <h3>Проверка по реплею</h3>
    <p>Отметьте эпизоды, которые вы посмотрели со своей камеры.</p>
    {report.items.map(item=><label key={item.id} className="layer-toggle"><input type="checkbox" checked={!!progress.completed[item.id]} disabled={progress.saving} onChange={e=>void progress.toggle(item.id,e.target.checked)}/><span>{item.title}</span></label>)}
    <p className="training-save-status" role="status">{progress.status}</p>
    <h3>Вопросы по данным матча</h3><p className="fine-print">Поиск по сохранённым событиям и показателям. Для причин ошибок нужен полный реплей.</p>
    <form onSubmit={e=>{e.preventDefault();void ask();}}><label htmlFor="report-question">Ваш вопрос</label><textarea id="report-question" value={question} onChange={e=>setQuestion(e.target.value)} minLength={3} maxLength={1000} required placeholder="Какой был перевес по золоту в этот момент?"/><button type="submit" disabled={busy}>{busy ? "Проверяем…" : "Найти в разборе"}</button></form>
    {answer && <div className="report-answer"><p style={{whiteSpace:"pre-line"}}>{answer.text}</p>{answer.time&&<button type="button" onClick={()=>onSeek(answer.time!.type==="point" ? answer.time!.seconds : answer.time!.startSeconds)}>Показать событие</button>}</div>}
    {notice&&<p role="status">{notice}</p>}
  </section>;
}
