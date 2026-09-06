import {z} from "zod";
import {requireApiAccount,accountApiError} from "@/lib/auth/api-account";
import {videoService,videoJsonResponse} from "@/lib/video/service";
export const dynamic="force-dynamic";
export async function GET(request:Request,context:{params:Promise<{id:string}>}){try{
  const {account}=await requireApiAccount();const id=z.string().uuid().parse((await context.params).id);
  const range=request.headers.get("range");const response=await videoService(account.id,`/v1/videos/${id}/source`,{stream:true,headers:range&&/^bytes=\d*-\d*$/.test(range)?{Range:range}:{}});
  if(!response.ok)return videoJsonResponse(response);
  const headers=new Headers({"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"});
  for(const key of ["Content-Type","Content-Length","Content-Range","Accept-Ranges"])if(response.headers.has(key))headers.set(key,response.headers.get(key)!);
  return new Response(response.body,{status:response.status,headers});
}catch(error){return accountApiError(error);}}
