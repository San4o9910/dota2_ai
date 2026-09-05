import {env} from "cloudflare:workers";
import {AccountApiError} from "@/lib/auth/api-account";
export async function requireReplayWorker(request:Request) {
  const runtime=env as unknown as {REPLAY_WORKER_TOKEN?:string;DB?:D1Database;REPLAYS?:R2Bucket};
  const token=runtime.REPLAY_WORKER_TOKEN;
  if(!token||token.length<32||!runtime.DB||!runtime.REPLAYS)throw new AccountApiError("Обработчик реплеев недоступен.",503);
  const header=request.headers.get("authorization")??"";
  if(header.length>1024)throw new AccountApiError("Нет доступа.",401);
  const digest=async(value:string)=>new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(value)));
  const [actual,expected]=await Promise.all([digest(header),digest(`Bearer ${token}`)]);let different=0;
  for(let i=0;i<expected.length;i++)different|=actual[i]^expected[i];
  if(different)throw new AccountApiError("Нет доступа.",401);
  return {db:runtime.DB,bucket:runtime.REPLAYS};
}
