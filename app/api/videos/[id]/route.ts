import {z} from "zod";
import {requireApiAccount,accountApiError} from "@/lib/auth/api-account";
import {videoService,videoJsonResponse,videoPart} from "@/lib/video/service";
export const dynamic="force-dynamic";
type Context={params:Promise<{id:string}>};
async function id(context:Context){return z.string().uuid().parse((await context.params).id);}
export async function GET(request:Request,context:Context){try{
  const {account}=await requireApiAccount();const job=await id(context);const after=z.coerce.number().int().min(-1).max(432000).parse(new URL(request.url).searchParams.get("after")??-1);
  return videoJsonResponse(await videoService(account.id,`/v1/videos/${job}?after=${after}`));
}catch(error){return accountApiError(error);}}
export async function PUT(request:Request,context:Context){try{
  const {account}=await requireApiAccount(request);const job=await id(context);const part=z.coerce.number().int().min(1).max(410).parse(new URL(request.url).searchParams.get("part"));
  return videoJsonResponse(await videoService(account.id,`/v1/videos/${job}/parts/${part}`,{method:"PUT",headers:{"Content-Type":"application/octet-stream"},body:await videoPart(request)}));
}catch(error){return accountApiError(error);}}
export async function POST(request:Request,context:Context){try{
  const {account}=await requireApiAccount(request);const job=await id(context);
  return videoJsonResponse(await videoService(account.id,`/v1/videos/${job}/complete`,{method:"POST"}));
}catch(error){return accountApiError(error);}}
export async function DELETE(request:Request,context:Context){try{
  const {account}=await requireApiAccount(request);const job=await id(context);
  return videoJsonResponse(await videoService(account.id,`/v1/videos/${job}`,{method:"DELETE"}));
}catch(error){return accountApiError(error);}}
