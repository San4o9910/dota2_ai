import {requireReplayWorker} from "@/lib/replay/worker-auth";
import {accountApiError,accountJson,AccountApiError} from "@/lib/auth/api-account";
import {readBoundedJson} from "@/lib/security/bounded-json";
import {OpenDotaMatchSchema} from "@/lib/analysis/opendota";
import {normalizeOpenDotaMatch} from "@/lib/analysis/normalizer";
import {canonicalJson} from "@/lib/analysis/canonical-json";
import {z} from "zod";
import {extractIdentityRoster} from "@/lib/dota/player-identity";
export const dynamic="force-dynamic";
type Context={params:Promise<{id:string}>};
async function leased(request:Request,context:Context,allowReady=false){const runtime=await requireReplayWorker(request);const {id}=await context.params;const token=request.headers.get("x-replay-lease");if(!token||!/^[0-9a-f-]{36}$/i.test(id))throw new AccountApiError("Задание не найдено.",404);const row=await runtime.db.prepare("SELECT id,object_key AS objectKey,size_bytes AS sizeBytes,state,normalized_payload AS payload,identity_payload AS identities FROM replay_uploads WHERE id=?1 AND ((state='processing' AND lease_token=?2 AND lease_expires_at>CURRENT_TIMESTAMP) OR (?3=1 AND state='ready' AND completion_token=?2))").bind(id,token,allowReady?1:0).first<{id:string;objectKey:string;sizeBytes:number;state:string;payload:string|null;identities:string|null}>();if(!row)throw new AccountApiError("Задание больше не принадлежит обработчику.",409);return {...runtime,row,token};}
export async function GET(request:Request,context:Context){try{const {row,bucket}=await leased(request,context);const object=await bucket.get(row.objectKey);if(!object)throw new AccountApiError("Исходный файл не найден.",404);return new Response(object.body,{headers:{"Content-Type":"application/octet-stream","Content-Length":String(object.size),"Cache-Control":"no-store"}});}catch(e){return accountApiError(e);}}
export async function POST(request:Request,context:Context){try{
  const {db,row,token}=await leased(request,context,true);
  const input=z.object({match:OpenDotaMatchSchema}).strict().parse(await readBoundedJson(request,8*1024*1024));
  const match=normalizeOpenDotaMatch(input.match);const payload=canonicalJson(match);
  const identities=canonicalJson(extractIdentityRoster(input.match.players));
  if(new TextEncoder().encode(payload).byteLength>1500000)throw new AccountApiError("Результат обработки слишком велик.",413);
  if(row.state==="ready") {
    if(row.payload!==payload || row.identities!==identities)throw new AccountApiError("Результат уже сохранён с другими данными.",409);
    return accountJson({ready:true,matchId:match.matchId});
  }
  const result=await db.prepare("UPDATE replay_uploads SET state='ready',match_id=?1,normalized_payload=?2,identity_payload=?5,completion_token=?4,lease_token=NULL,lease_expires_at=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?3 AND state='processing' AND lease_token=?4 AND lease_expires_at>CURRENT_TIMESTAMP").bind(match.matchId,payload,row.id,token,identities).run();
  if(!result.meta.changes)throw new AccountApiError("Задание передано другому обработчику.",409);
  return accountJson({ready:true,matchId:match.matchId});
}catch(e){return accountApiError(e);}}
export async function DELETE(request:Request,context:Context){try{const {db,row,token}=await leased(request,context);await db.prepare("UPDATE replay_uploads SET state='failed',failure_code='REPLAY_PARSE_FAILED',lease_token=NULL,lease_expires_at=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?1 AND lease_token=?2 AND state='processing'").bind(row.id,token).run();return accountJson({failed:true});}catch(e){return accountApiError(e);}}
