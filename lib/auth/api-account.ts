import { getChatGPTUser } from "@/app/chatgpt-auth";
import { getCurrentAccount, getOrCreateCurrentAccount } from "@/lib/auth/current-account";
import { getAnalysisRuntime } from "@/lib/analyses/runtime";
import { isSameOriginRequest } from "@/lib/security/same-origin";
import { BoundedJsonError } from "@/lib/security/bounded-json";
import { ZodError } from "zod";
import { AnalysisRouteError } from "@/lib/analyses/errors";
import { AnalysisError } from "@/lib/analysis/errors";
import { ScanRouteError } from "@/lib/scan/errors";

export class AccountApiError extends Error { constructor(message:string,public status:number) {super(message);} }
export async function requireApiAccount(request?:Request,create=false) {
  if(request && !isSameOriginRequest(request)) throw new AccountApiError("Откройте страницу приложения и повторите запрос.",403);
  const identity=await getChatGPTUser();
  if(!identity) throw new AccountApiError("Войдите в аккаунт.",401);
  const account=create ? await getOrCreateCurrentAccount(identity) : await getCurrentAccount(identity);
  if(!account || account.status!=="active"||account.deletedAt) throw new AccountApiError("Аккаунт недоступен.",403);
  const db=getAnalysisRuntime().db;
  if(!db) throw new AccountApiError("Сохранение временно недоступно.",503);
  return {account,identity,db};
}
export function accountJson(body:unknown,status=200) {return Response.json(body,{status,headers:{"Cache-Control":"no-store"}});}
export function accountApiError(error:unknown) {
  if(error instanceof AnalysisRouteError || error instanceof AnalysisError || error instanceof ScanRouteError) {
    const requestId=crypto.randomUUID();
    if(error.httpStatus>=500) console.error(JSON.stringify({event:"account_api_failure",requestId,code:error.code,status:error.httpStatus}));
    const response=accountJson({error:error.message,code:error.code,retryable:error.retryable,requestId},error.httpStatus);
    if(error.retryAfterSeconds!==undefined)response.headers.set("Retry-After",String(error.retryAfterSeconds));
    return response;
  }
  if(error instanceof AccountApiError) return accountJson({error:error.message},error.status);
  if(error instanceof ZodError || error instanceof BoundedJsonError) return accountJson({error:"Проверьте данные запроса."},400);
  const requestId=crypto.randomUUID();console.error(JSON.stringify({event:"account_api_failure",requestId,code:"UNEXPECTED_ACCOUNT_ERROR",status:503}));
  return accountJson({error:"Не удалось сохранить изменения. Попробуйте ещё раз.",requestId},503);
}
