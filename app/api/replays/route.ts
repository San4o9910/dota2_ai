import {z} from "zod";
import {accountApiError,accountJson,requireApiAccount,AccountApiError} from "@/lib/auth/api-account";
import {readBoundedJson} from "@/lib/security/bounded-json";
import {replayBucket,REPLAY_MAX_BYTES,REPLAY_PART_BYTES,UPLOAD_COLUMNS,publicUpload,type UploadRow} from "@/lib/replay/uploads";
export const dynamic="force-dynamic";
const schema=z.object({filename:z.string().min(5).max(180).regex(/^[^\x00-\x1f\x7f/\\]+\.dem(?:\.bz2)?$/),sizeBytes:z.number().int().min(16).max(REPLAY_MAX_BYTES)}).strict();
export async function GET(){try{const {account,db}=await requireApiAccount();let enabled=true;try{replayBucket();}catch{enabled=false;}const rows=await db.prepare(`SELECT ${UPLOAD_COLUMNS} FROM replay_uploads WHERE user_id=?1 AND state<>'deleted' ORDER BY created_at DESC LIMIT 30`).bind(account.id).all<UploadRow>();return accountJson({enabled,uploads:rows.results.map(publicUpload),maxBytes:REPLAY_MAX_BYTES});}catch(e){return accountApiError(e);}}
export async function POST(request:Request){
  try{
    const {account,db}=await requireApiAccount(request,true);const bucket=replayBucket();
    const input=schema.parse(await readBoundedJson(request,4096));const requestKey=request.headers.get("Idempotency-Key");
    if(!requestKey||!z.string().uuid().safeParse(requestKey).success)throw new AccountApiError("Повторите загрузку со страницы реплеев.",400);
    const id=requestKey;const existing=await db.prepare(`SELECT ${UPLOAD_COLUMNS} FROM replay_uploads WHERE id=?1`).bind(id).first<UploadRow>();
    if(existing){
      if(existing.userId!==account.id||existing.filename!==input.filename||existing.sizeBytes!==input.sizeBytes)throw new AccountApiError("Этот запрос уже связан с другим файлом.",409);
      if(existing.state!=="uploading"||!existing.uploadId)throw new AccountApiError("Эта загрузка уже завершена или прервана. Проверьте список файлов; прерванную загрузку можно удалить.",409);
      return accountJson({id,partBytes:REPLAY_PART_BYTES,partCount:Math.ceil(input.sizeBytes/REPLAY_PART_BYTES)});
    }
    const key=`replays/${account.id}/${id}/source`;
    const insert=await db.prepare(`INSERT INTO replay_uploads(id,user_id,filename,object_key,size_bytes)
      SELECT ?1,?2,?3,?4,?5 WHERE (SELECT COUNT(*) FROM replay_uploads WHERE user_id=?2 AND created_at>datetime(CURRENT_TIMESTAMP,'-1 day'))<4
      AND (SELECT COALESCE(SUM(size_bytes),0) FROM replay_uploads WHERE user_id=?2 AND state<>'deleted')+?5<=?6 ON CONFLICT(id) DO NOTHING`).bind(id,account.id,input.filename,key,input.sizeBytes,2*REPLAY_MAX_BYTES).run();
    if(!insert.meta.changes)throw new AccountApiError("Лимит загрузки исчерпан. Удалите ненужные реплеи или повторите завтра.",429);
    let multipart:R2MultipartUpload|null=null;
    try{multipart=await bucket.createMultipartUpload(key,{httpMetadata:{contentType:"application/octet-stream"},customMetadata:{replayId:id}});const saved=await db.prepare("UPDATE replay_uploads SET upload_id=?1 WHERE id=?2 AND state='uploading'").bind(multipart.uploadId,id).run();if(!saved.meta.changes)throw new AccountApiError("Загрузка отменена.",409);}
    catch(e){if(multipart)await multipart.abort().catch(()=>{});await db.prepare("UPDATE replay_uploads SET state='failed',failure_code='UPLOAD_INIT_FAILED',updated_at=CURRENT_TIMESTAMP WHERE id=?1 AND state='uploading'").bind(id).run();throw e;}
    return accountJson({id,partBytes:REPLAY_PART_BYTES,partCount:Math.ceil(input.sizeBytes/REPLAY_PART_BYTES)},201);
  }catch(e){return accountApiError(e);}
}
