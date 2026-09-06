import {z} from "zod";
import {requireApiAccount,accountApiError,accountJson,AccountApiError} from "@/lib/auth/api-account";
import {D1PlayerBindingStore} from "@/lib/dota/player-binding";
import {readBoundedJson} from "@/lib/security/bounded-json";
import {videoService,videoServiceConfigured,videoJsonResponse} from "@/lib/video/service";
export const dynamic="force-dynamic";
const create=z.object({id:z.string().uuid(),filename:z.string().min(5).max(180),size_bytes:z.number().int().min(16).max(2*1024**3)}).strict();
export async function GET(){try{const {account}=await requireApiAccount(undefined,true);
  if(!videoServiceConfigured())return accountJson({videos:[],configured:false,worker_ready:false});
  return videoJsonResponse(await videoService(account.id,"/v1/videos"));
}catch(error){return accountApiError(error);}}
export async function POST(request:Request){try{const {account,db}=await requireApiAccount(request,true);
  const input=create.parse(await readBoundedJson(request,4096));const profile=await new D1PlayerBindingStore(db).get(account.id);
  if(!profile)throw new AccountApiError("Сначала закрепите свой профиль Dota по реплею в разделе разборов.",409);
  return videoJsonResponse(await videoService(account.id,"/v1/videos",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...input,account_id:profile.accountId,nickname:profile.nickname})}));
}catch(error){return accountApiError(error);}}
