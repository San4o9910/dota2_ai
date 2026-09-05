import {env} from "cloudflare:workers";
import {AccountApiError} from "@/lib/auth/api-account";
export const REPLAY_PART_BYTES=5*1024*1024;
export const REPLAY_MAX_BYTES=512*1024*1024;
export function replayBucket() {const bucket=(env as unknown as {REPLAYS?:R2Bucket}).REPLAYS;if(!bucket)throw new AccountApiError("Загрузка реплеев пока недоступна.",503);return bucket;}
export type UploadRow={id:string;userId:string;filename:string;objectKey:string;uploadId:string|null;sizeBytes:number;state:string;failureCode:string|null;matchId:string|null;createdAt:string};
export const UPLOAD_COLUMNS="id,user_id AS userId,filename,object_key AS objectKey,upload_id AS uploadId,size_bytes AS sizeBytes,state,failure_code AS failureCode,match_id AS matchId,created_at AS createdAt";
export async function ownedUpload(db:D1Database,userId:string,id:string){
  if(!/^[0-9a-f-]{36}$/i.test(id))throw new AccountApiError("Реплей не найден.",404);
  const row=await db.prepare(`SELECT ${UPLOAD_COLUMNS} FROM replay_uploads WHERE id=?1 AND user_id=?2 AND state<>'deleted'`).bind(id,userId).first<UploadRow>();
  if(!row)throw new AccountApiError("Реплей не найден.",404);return row;
}
export function publicUpload(row:UploadRow){return {id:row.id,filename:row.filename,sizeBytes:row.sizeBytes,state:row.state,matchId:row.matchId,createdAt:row.createdAt};}
export async function lockUpload(db:D1Database,userId:string,id:string,allowExpired=false){
  const token=crypto.randomUUID();
  const result=await db.prepare(`UPDATE replay_uploads SET lease_token=?1,lease_expires_at=datetime(CURRENT_TIMESTAMP,'+90 seconds')
    WHERE id=?2 AND user_id=?3 AND state<>'deleted' AND (state<>'processing' OR (?4=1 AND lease_expires_at<=CURRENT_TIMESTAMP))
      AND (upload_id IS NOT NULL OR ?4=1) AND (lease_token IS NULL OR (?4=1 AND lease_expires_at<=CURRENT_TIMESTAMP))
    RETURNING ${UPLOAD_COLUMNS}`).bind(token,id,userId,allowExpired ? 1:0).first<UploadRow>();
  if(!result)throw new AccountApiError("Файл занят. Если повтор не помогает, удалите прерванную загрузку и загрузите файл заново.",409);
  return {row:result,token,release:()=>db.prepare("UPDATE replay_uploads SET lease_token=NULL,lease_expires_at=NULL WHERE id=?1 AND lease_token=?2 AND state<>'processing'").bind(id,token).run()};
}
export async function readReplayPart(request:Request,expected:number){
  if(Number(request.headers.get("content-length")||0)>expected)throw new AccountApiError("Часть файла слишком велика.",413);
  const reader=request.body?.getReader();if(!reader)throw new AccountApiError("Нет данных файла.",400);
  const result=new Uint8Array(expected);let length=0;
  try{while(true){const {value,done}=await reader.read();if(done)break;length+=value.byteLength;if(length>expected){await reader.cancel();throw new AccountApiError("Часть файла слишком велика.",413);}result.set(value,length-value.byteLength);}}
  finally{reader.releaseLock();}
  if(length!==expected)throw new AccountApiError("Часть файла передана не полностью. Повторите загрузку.",400);
  return result;
}
export function validReplaySignature(bytes:Uint8Array,filename:string){
  const header=new TextDecoder().decode(bytes.subarray(0,8));
  return filename.endsWith(".dem.bz2") ? /^BZh[1-9]/.test(header) : header==="PBDEMS2\0";
}
