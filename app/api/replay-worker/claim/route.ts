import {requireReplayWorker} from "@/lib/replay/worker-auth";
import {accountApiError,accountJson,AccountApiError} from "@/lib/auth/api-account";
export const dynamic="force-dynamic";
export async function POST(request:Request){try{
  const {db}=await requireReplayWorker(request);const leaseToken=request.headers.get("Idempotency-Key");
  if(!leaseToken||!/^[0-9a-f-]{36}$/i.test(leaseToken))throw new AccountApiError("Укажите ключ запроса.",400);
  const previous=await db.prepare("SELECT id,filename,size_bytes AS sizeBytes FROM replay_uploads WHERE state='processing' AND lease_token=?1 AND lease_expires_at>CURRENT_TIMESTAMP").bind(leaseToken).first();
  if(previous)return accountJson({job:{...previous,leaseToken}});
  await db.prepare("UPDATE replay_uploads SET state='failed',failure_code='PARSER_ATTEMPTS_EXHAUSTED',lease_token=NULL,lease_expires_at=NULL,updated_at=CURRENT_TIMESTAMP WHERE state='processing' AND lease_expires_at<=CURRENT_TIMESTAMP AND attempt>=3").run();
  const job=await db.prepare(`UPDATE replay_uploads SET state='processing',attempt=attempt+1,lease_token=?1,lease_expires_at=datetime(CURRENT_TIMESTAMP,'+20 minutes'),updated_at=CURRENT_TIMESTAMP
    WHERE id=(SELECT id FROM replay_uploads WHERE ((state='uploaded' AND (lease_token IS NULL OR lease_expires_at<=CURRENT_TIMESTAMP)) OR (state='processing' AND lease_expires_at<=CURRENT_TIMESTAMP)) AND attempt<3 AND EXISTS(SELECT 1 FROM users WHERE users.id=replay_uploads.user_id AND users.status='active' AND users.deleted_at IS NULL) AND NOT EXISTS(SELECT 1 FROM replay_uploads WHERE lease_token=?1 AND state='processing' AND lease_expires_at>CURRENT_TIMESTAMP) ORDER BY created_at LIMIT 1)
    RETURNING id,filename,size_bytes AS sizeBytes`).bind(leaseToken).first();
  const claimed=job??await db.prepare("SELECT id,filename,size_bytes AS sizeBytes FROM replay_uploads WHERE lease_token=?1 AND state='processing' AND lease_expires_at>CURRENT_TIMESTAMP").bind(leaseToken).first();
  return accountJson({job:claimed ? {...claimed,leaseToken} : null});
}catch(e){return accountApiError(e);}}
