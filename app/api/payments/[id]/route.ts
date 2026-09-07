import { accountApiError, accountJson, requireApiAccount, AccountApiError } from "@/lib/auth/api-account";
import { POST as settleNotification } from "@/app/api/payments/webhook/route";
import { D1FixedWindowRateLimiter } from "@/lib/scan/storage";
import { canonicalSha256 } from "@/lib/analysis/canonical-json";

export const dynamic = "force-dynamic";
type Context = { params: Promise<{id:string}> };
async function owned(context:Context, request?:Request) {
  const {account,db}=await requireApiAccount(request);
  const {id}=await context.params;
  if(!/^[0-9a-f-]{36}$/i.test(id))throw new AccountApiError("Заказ не найден.",404);
  const order=await db.prepare(`SELECT id,payment_status AS paymentStatus,
    fulfillment_status AS fulfillmentStatus,amount_kopecks AS amountKopecks,
    product_code AS productCode,yookassa_payment_id AS providerId
    FROM orders WHERE id=?1 AND user_id=?2`).bind(id,account.id).first<{
      id:string;paymentStatus:string;fulfillmentStatus:string;amountKopecks:number;productCode:string;providerId:string|null;
    }>();
  if(!order)throw new AccountApiError("Заказ не найден.",404);
  return {account,db,order};
}
export async function GET(_request:Request,context:Context) {
  try { const {order}=await owned(context);const {providerId,...status}=order;return accountJson({order:status,canRefresh:!!providerId}); }
  catch(error){return accountApiError(error);}
}
export async function POST(request:Request,context:Context) {
  try {
    const {account,db,order}=await owned(context,request);
    if(!order.providerId)throw new AccountApiError("Подтверждение заказа ещё не получено. Проверка этого платежа требует поддержки.",409);
    const limit=await new D1FixedWindowRateLimiter(db).take(await canonicalSha256({scope:"payment_refresh",owner:account.id}),Date.now());
    if(!limit.allowed)throw new AccountApiError("Подождите несколько минут перед следующей проверкой.",429);
    // This internal notification is only a trigger. The shared settlement path
    // independently fetches YooKassa and checks the frozen order identity.
    const result=await settleNotification(new Request(new URL("/api/payments/webhook",request.url),{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({event:"payment.succeeded",object:{id:order.providerId}}),
    }));
    if(!result.ok)throw new AccountApiError("Подтверждение оплаты пока не получено. Повторите проверку позже.",503);
    return GET(request,context);
  }catch(error){return accountApiError(error);}
}
