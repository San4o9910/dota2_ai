import { handleScanPost, scanDisabledResponse } from "@/lib/scan/handler";
import { getScanRuntime } from "@/lib/scan/runtime";
import { D1FixedWindowRateLimiter, D1ScanMatchCache } from "@/lib/scan/storage";
import { requireApiAccount,accountApiError } from "@/lib/auth/api-account";
import { D1PlayerBindingStore } from "@/lib/dota/player-binding";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
  const {account}=await requireApiAccount(request,true);
  const runtime = getScanRuntime();
  if (!runtime) return scanDisabledResponse(request);

  return handleScanPost(request, {
    cache: new D1ScanMatchCache(runtime.db),
    rateLimiter: new D1FixedWindowRateLimiter(runtime.db),
    rateLimitSecret: runtime.rateLimitSecret,
    resolveTarget: input => new D1PlayerBindingStore(runtime.db).resolve(account.id,input,{signal:request.signal}),
  });
  } catch(error) { return accountApiError(error); }
}
