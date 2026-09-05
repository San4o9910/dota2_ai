import {NormalizedMatchV1Schema} from "@/lib/analysis/contracts";
import {buildEvidenceBundle} from "@/lib/analysis/normalizer";
import {accountApiError,accountJson,requireApiAccount,AccountApiError} from "@/lib/auth/api-account";
import {lockUpload,ownedUpload,replayBucket,REPLAY_PART_BYTES,readReplayPart,validReplaySignature,publicUpload} from "@/lib/replay/uploads";
export const dynamic="force-dynamic";
type Context={params:Promise<{id:string}>};
export async function GET(_request:Request,context:Context){try{const {account,db}=await requireApiAccount();const {id}=await context.params;const row=await ownedUpload(db,account.id,id);const parts=await db.prepare("SELECT part_number AS partNumber,size_bytes AS sizeBytes FROM replay_upload_parts WHERE replay_id=?1 ORDER BY part_number").bind(id).all();const result=row.state==="ready" ? await db.prepare("SELECT normalized_payload AS payload FROM replay_uploads WHERE id=?1 AND user_id=?2").bind(id,account.id).first<{payload:string|null}>() : null;const match=result?.payload ? NormalizedMatchV1Schema.parse(JSON.parse(result.payload)) : null;return accountJson({upload:publicUpload(row),parts:parts.results,match,evidenceBundle:match ? (await buildEvidenceBundle(match)).evidenceBundle : null});}catch(e){return accountApiError(e);}}
export async function PUT(request:Request,context:Context){
  let operation:Awaited<ReturnType<typeof lockUpload>>|null=null;
  try{
    const {account,db}=await requireApiAccount(request);const {id}=await context.params;await ownedUpload(db,account.id,id);operation=await lockUpload(db,account.id,id);const {row}=operation;
    if(row.state!=="uploading"||!row.uploadId)throw new AccountApiError("Загрузка уже завершена или отменена.",409);
    const part=Number(new URL(request.url).searchParams.get("part"));const count=Math.ceil(row.sizeBytes/REPLAY_PART_BYTES);
    if(!Number.isInteger(part)||part<1||part>count)throw new AccountApiError("Неверный номер части файла.",400);
    const expected=Math.min(REPLAY_PART_BYTES,row.sizeBytes-(part-1)*REPLAY_PART_BYTES);const bytes=await readReplayPart(request,expected);
    if(part===1&&!validReplaySignature(bytes,row.filename))throw new AccountApiError("Это не реплей Dota 2. Выберите исходный .dem или .dem.bz2.",415);
    const uploaded=await replayBucket().resumeMultipartUpload(row.objectKey,row.uploadId).uploadPart(part,bytes);
    const recorded=await db.prepare(`INSERT INTO replay_upload_parts(id,replay_id,part_number,etag,size_bytes)
      SELECT ?1,?2,?3,?4,?5 WHERE EXISTS(SELECT 1 FROM replay_uploads WHERE id=?2 AND state='uploading' AND lease_token=?6 AND lease_expires_at>CURRENT_TIMESTAMP)
      ON CONFLICT(replay_id,part_number) DO UPDATE SET etag=excluded.etag,size_bytes=excluded.size_bytes`).bind(`${id}:${part}`,id,part,uploaded.etag,expected,operation.token).run();
    if(!recorded.meta.changes)throw new AccountApiError("Загрузка отменена.",409);
    return accountJson({partNumber:part,uploaded:true});
  }catch(e){return accountApiError(e);}finally{if(operation)await operation.release().catch(()=>console.error("replay_operation_unlock_failed"));}
}
export async function POST(request:Request,context:Context){
  let operation:Awaited<ReturnType<typeof lockUpload>>|null=null;
  try{
    const {account,db}=await requireApiAccount(request);const {id}=await context.params;await ownedUpload(db,account.id,id);operation=await lockUpload(db,account.id,id);const {row}=operation;
    if(row.state==="uploaded"||row.state==="ready"||row.state==="processing")return accountJson({upload:publicUpload(row)});
    if(row.state!=="uploading"||!row.uploadId)throw new AccountApiError("Эту загрузку нельзя завершить.",409);
    const parts=await db.prepare("SELECT part_number AS partNumber,etag,size_bytes AS sizeBytes FROM replay_upload_parts WHERE replay_id=?1 ORDER BY part_number").bind(id).all<{partNumber:number;etag:string;sizeBytes:number}>();
    if(parts.results.length!==Math.ceil(row.sizeBytes/REPLAY_PART_BYTES)||parts.results.some((p,i)=>p.partNumber!==i+1)||parts.results.reduce((sum,p)=>sum+p.sizeBytes,0)!==row.sizeBytes)throw new AccountApiError("Переданы не все части. Продолжите загрузку.",409);
    const bucket=replayBucket();
    const existing=await bucket.head(row.objectKey);
    if(!existing)await bucket.resumeMultipartUpload(row.objectKey,row.uploadId).complete(parts.results.map(({partNumber,etag})=>({partNumber,etag})));
    const stored=await bucket.head(row.objectKey);
    if(!stored||stored.size!==row.sizeBytes)throw new AccountApiError("Размер сохранённого реплея не совпал. Повторите загрузку.",503);
    const completed=await db.prepare("UPDATE replay_uploads SET state='uploaded',updated_at=CURRENT_TIMESTAMP WHERE id=?1 AND user_id=?2 AND state='uploading' AND lease_token=?3 AND lease_expires_at>CURRENT_TIMESTAMP").bind(id,account.id,operation.token).run();
    if(!completed.meta.changes){await bucket.delete(row.objectKey);throw new AccountApiError("Загрузка отменена.",409);}
    return accountJson({upload:{...publicUpload(row),state:"uploaded"}});
  }catch(e){return accountApiError(e);}finally{if(operation)await operation.release().catch(()=>console.error("replay_operation_unlock_failed"));}
}
export async function DELETE(request:Request,context:Context){
  let operation:Awaited<ReturnType<typeof lockUpload>>|null=null;
  try{const {account,db}=await requireApiAccount(request);const {id}=await context.params;
    operation=await lockUpload(db,account.id,id,true);const {row}=operation;const bucket=replayBucket();
    await db.prepare("UPDATE replay_uploads SET state='failed',failure_code='DELETE_PENDING',updated_at=CURRENT_TIMESTAMP WHERE id=?1 AND lease_token=?2").bind(id,operation.token).run();
    if(row.uploadId && !await bucket.head(row.objectKey) && !["uploaded","ready","processing"].includes(row.state)) {
      try { await bucket.resumeMultipartUpload(row.objectKey,row.uploadId).abort(); }
      catch(error) { if(!(error instanceof Error) || !/NoSuchUpload|does not exist|not found|already (aborted|completed)|10024/i.test(error.message))throw error; }
    }
    await bucket.delete(row.objectKey);
    await db.batch([
      db.prepare("DELETE FROM replay_upload_parts WHERE replay_id=?1").bind(id),
      db.prepare("UPDATE replay_uploads SET state='deleted',failure_code=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?1 AND lease_token=?2").bind(id,operation.token),
    ]);
    return accountJson({deleted:true});
  }catch(e){return accountApiError(e);}finally{if(operation)await operation.release().catch(()=>console.error("replay_operation_unlock_failed"));}
}
