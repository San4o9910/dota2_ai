import { z } from "zod";
import { TRAINING_PLAN } from "@/app/data/training-plan";
import { ANALYSIS_ID_PATTERN } from "@/lib/analyses/contracts";
import { D1AnalysisStore } from "@/lib/analyses/store";
import { AccountApiError,accountApiError,accountJson,requireApiAccount } from "@/lib/auth/api-account";
import { readBoundedJson } from "@/lib/security/bounded-json";

export const dynamic="force-dynamic";
const contextSchema=z.string().refine(v=>v==="demo:8963624400"||ANALYSIS_ID_PATTERN.test(v));
const updateSchema=z.object({contextId:contextSchema,taskId:z.string().min(1).max(100),completed:z.boolean()}).strict();
const demoTasks=new Set(Object.values(TRAINING_PLAN).flatMap(stage=>stage.drills.map(d=>d.id)));

export async function GET(request:Request) {
  try {
    const {account,db}=await requireApiAccount();
    const contextId=new URL(request.url).searchParams.get("context");
    if(contextId) contextSchema.parse(contextId);
    const query=contextId ? db.prepare("SELECT context_id AS contextId,task_id AS taskId,completed,updated_at AS updatedAt FROM training_progress WHERE user_id=?1 AND context_id=?2 ORDER BY updated_at DESC LIMIT 100").bind(account.id,contextId)
      :db.prepare("SELECT context_id AS contextId,task_id AS taskId,completed,updated_at AS updatedAt FROM training_progress WHERE user_id=?1 ORDER BY updated_at DESC LIMIT 200").bind(account.id);
    return accountJson({progress:(await query.all()).results});
  } catch(error) {return accountApiError(error);}
}
export async function PUT(request:Request) {
  try {
    const {account,db}=await requireApiAccount(request,true);
    const input=updateSchema.parse(await readBoundedJson(request,4096));
    if(input.contextId==="demo:8963624400") {
      if(!demoTasks.has(input.taskId)) throw new AccountApiError("Упражнение не найдено.",404);
    } else {
      const detail=await new D1AnalysisStore(db).getOwned(account.id,input.contextId);
      if(detail?.job.state!=="ready" || !detail.report?.items.some(i=>i.id===input.taskId)) throw new AccountApiError("Упражнение не найдено.",404);
    }
    await db.prepare(`INSERT INTO training_progress(id,user_id,context_id,task_id,completed) VALUES(?1,?2,?3,?4,?5)
      ON CONFLICT(user_id,context_id,task_id) DO UPDATE SET completed=excluded.completed,updated_at=CURRENT_TIMESTAMP`).bind(crypto.randomUUID(),account.id,input.contextId,input.taskId,input.completed?1:0).run();
    return accountJson({saved:true,...input});
  } catch(error) {return accountApiError(error);}
}
