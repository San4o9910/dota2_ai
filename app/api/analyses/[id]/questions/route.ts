import {canonicalSha256} from "@/lib/analysis/canonical-json";
import {z} from "zod";
import {accountApiError,accountJson,requireApiAccount,AccountApiError} from "@/lib/auth/api-account";
import {ANALYSIS_ID_PATTERN} from "@/lib/analyses/contracts";
import {D1AnalysisStore} from "@/lib/analyses/store";
import {readBoundedJson} from "@/lib/security/bounded-json";
import {answerFromMatch} from "@/lib/coaching/questions";
export const dynamic="force-dynamic";
const schema=z.object({id:z.string().uuid(),question:z.string().trim().min(3).max(1000),time:z.number().int().min(-600).max(43200).nullable()}).strict();
export async function GET(_request:Request,context:{params:Promise<{id:string}>}) {
  try{
    const {account,db}=await requireApiAccount();const {id}=await context.params;
    if(!ANALYSIS_ID_PATTERN.test(id)||!await new D1AnalysisStore(db).getOwned(account.id,id))throw new AccountApiError("Разбор не найден.",404);
    const rows=await db.prepare("SELECT id,question,answer,created_at AS createdAt FROM coach_exchanges WHERE user_id=?1 AND job_id=?2 ORDER BY created_at DESC,id DESC LIMIT 30").bind(account.id,id).all();
    return accountJson({exchanges:rows.results.reverse()});
  }catch(error){return accountApiError(error);}
}
export async function POST(request:Request,context:{params:Promise<{id:string}>}) {
  try{
    const {account,db}=await requireApiAccount(request);const {id}=await context.params;
    if(!ANALYSIS_ID_PATTERN.test(id))throw new AccountApiError("Разбор не найден.",404);
    const detail=await new D1AnalysisStore(db).getOwned(account.id,id);
    if(!detail?.evidenceBundle||detail.job.state!=="ready")throw new AccountApiError("Разбор ещё недоступен.",404);
    const input=schema.parse(await readBoundedJson(request,4096));
    if(input.time!==null&&input.time>detail.evidenceBundle.durationSeconds)throw new AccountApiError("Этого времени нет в матче.",400);
    const requestHash=await canonicalSha256(input);
    const answer=answerFromMatch(detail.evidenceBundle,input.question,input.time,detail.job.playerSlot);
    // These bounded factual lookups are free; no paid coaching entitlement is consumed.
    await db.prepare(`INSERT INTO coach_exchanges(id,user_id,job_id,question,answer,request_hash)
      SELECT ?1,?2,?3,?4,?5,?6 WHERE (SELECT COUNT(*) FROM coach_exchanges WHERE user_id=?2 AND created_at>datetime(CURRENT_TIMESTAMP,'-1 day'))<60
      ON CONFLICT(id) DO NOTHING`).bind(input.id,account.id,id,input.question,JSON.stringify(answer),requestHash).run();
    const saved=await db.prepare("SELECT question,answer,request_hash AS requestHash FROM coach_exchanges WHERE id=?1 AND user_id=?2 AND job_id=?3").bind(input.id,account.id,id).first<{question:string;answer:string;requestHash:string|null}>();
    if(!saved)throw new AccountApiError("Лимит вопросов на сегодня исчерпан.",429);
    if(saved.question!==input.question||saved.requestHash!==requestHash)throw new AccountApiError("Этот запрос уже использован для другого вопроса.",409);
    return accountJson({id:input.id,answer:JSON.parse(saved.answer)});
  }catch(error){return accountApiError(error);}
}
