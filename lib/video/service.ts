import { env } from "cloudflare:workers";
import { AccountApiError } from "@/lib/auth/api-account";

export function videoServiceConfigured() {
  const config=env as unknown as {VIDEO_SERVICE_ORIGIN?:string;VIDEO_SERVICE_TOKEN?:string};
  return !!config.VIDEO_SERVICE_ORIGIN && (config.VIDEO_SERVICE_TOKEN?.length??0)>=32;
}
export async function videoService(ownerId:string,path:string,options:{method?:string;body?:BodyInit;headers?:Record<string,string>;stream?:boolean}={}) {
  const config=env as unknown as {VIDEO_SERVICE_ORIGIN?:string;VIDEO_SERVICE_TOKEN?:string};
  if(!videoServiceConfigured())throw new AccountApiError("Сервис видеоанализа ещё не подключён.",503);
  const origin=new URL(config.VIDEO_SERVICE_ORIGIN!);
  if(origin.protocol!=="https:" || origin.username || origin.password || origin.pathname!=="/" || origin.search || origin.hash)
    throw new AccountApiError("Сервис видеоанализа ещё не настроен.",503);
  try {
    return await fetch(new URL(path,origin),{method:options.method??"GET",body:options.body,redirect:"error",signal:AbortSignal.timeout(options.stream?1800000:60000),
      headers:{Authorization:`Bearer ${config.VIDEO_SERVICE_TOKEN}`,"X-Narma-Owner":ownerId,...options.headers}});
  } catch {throw new AccountApiError("Сервис видеоанализа не ответил. Повторите запрос.",503);}
}
export async function videoJsonResponse(response:Response) {
  const reader=response.body?.getReader();if(!reader)throw new AccountApiError("Сервис видеоанализа вернул пустой ответ.",503);
  const chunks:Uint8Array[]=[];let size=0;
  try{while(true){const {value,done}=await reader.read();if(done)break;size+=value.byteLength;if(size>2*1024*1024){await reader.cancel();throw new AccountApiError("Ответ видеоанализа слишком велик.",503);}chunks.push(value);}}finally{reader.releaseLock();}
  const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.byteLength;}
  const raw=new TextDecoder().decode(bytes);
  let body:Record<string,unknown>;try{body=JSON.parse(raw);}catch{throw new AccountApiError("Сервис видеоанализа временно недоступен.",503);}
  if(!response.ok)throw new AccountApiError(typeof body.detail==="string"?body.detail:"Не удалось обработать запрос видео.",response.status>=500?503:response.status);
  return Response.json(body,{headers:{"Cache-Control":"no-store"}});
}
export async function videoPart(request:Request) {
  const reader=request.body?.getReader();if(!reader)throw new AccountApiError("Нет данных видео.",400);
  const bytes=new Uint8Array(5*1024*1024);let size=0;
  try{while(true){const {value,done}=await reader.read();if(done)break;if(size+value.length>bytes.length){await reader.cancel();throw new AccountApiError("Часть видео слишком велика.",413);}bytes.set(value,size);size+=value.length;}}
  finally{reader.releaseLock();}
  return bytes.subarray(0,size);
}
