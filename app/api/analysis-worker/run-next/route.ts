import {D1PlayerBindingStore} from "@/lib/dota/player-binding";
import {after} from "next/server";
import {requireReplayWorker} from "@/lib/replay/worker-auth";
import {accountApiError,accountJson,AccountApiError} from "@/lib/auth/api-account";
import {getAnalysisRuntime} from "@/lib/analyses/runtime";
import {D1AnalysisStore} from "@/lib/analyses/store";
import {runOwnedAnalysis} from "@/lib/analyses/service";
import {D1ScanMatchCache} from "@/lib/scan/storage";
export const dynamic="force-dynamic";
export async function POST(request:Request){try{
  const {db}=await requireReplayWorker(request);const runtime=getAnalysisRuntime();
  if(!runtime.fulfillmentReady||!runtime.apiKey||!runtime.model)throw new AccountApiError("Разборы временно недоступны.",503);
  const store=new D1AnalysisStore(db);
  const candidates=await db.prepare(`SELECT job.id,job.user_id AS userId FROM analysis_jobs AS job
    JOIN users ON users.id=job.user_id WHERE users.status='active' AND users.deleted_at IS NULL
    AND ((job.state='queued' AND (job.retry_not_before IS NULL OR job.retry_not_before<=CURRENT_TIMESTAMP))
      OR (job.state='running' AND job.lease_expires_at<=CURRENT_TIMESTAMP))
    ORDER BY job.updated_at,job.id LIMIT 25`).all<{id:string;userId:string}>();
  const signal=AbortSignal.timeout(25_000);
  const work=(async()=>{
    for(const job of candidates.results){
      if(signal.aborted)break;
      await store.reconcileOwned(job.userId);
      const result=await runOwnedAnalysis(job.userId,job.id,{store,cache:new D1ScanMatchCache(db),apiKey:runtime.apiKey!,model:runtime.model!,allowedModels:runtime.allowedModels,authorizeTarget:(userId,matchId,slot)=>new D1PlayerBindingStore(db).assertTarget(userId,matchId,slot),signal});
      if(result.outcome!=="busy"&&result.outcome!=="terminal")return {processed:true,outcome:result.outcome};
    }
    await db.prepare("DELETE FROM rate_limit_buckets WHERE id IN (SELECT id FROM rate_limit_buckets WHERE expires_at<?1 LIMIT 1000)").bind(Math.floor(Date.now()/1000)-86400).run();
    return {processed:false};
  })();
  after(work);return accountJson(await work);
}catch(error){return accountApiError(error);}}
