import { handleScanPost, scanDisabledResponse } from "@/lib/scan/handler";
import { getScanRuntime } from "@/lib/scan/runtime";
import { D1FixedWindowRateLimiter, D1ScanMatchCache } from "@/lib/scan/storage";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const runtime = getScanRuntime();
  if (!runtime) return scanDisabledResponse(request);

  return handleScanPost(request, {
    cache: new D1ScanMatchCache(runtime.db),
    rateLimiter: new D1FixedWindowRateLimiter(runtime.db),
    rateLimitSecret: runtime.rateLimitSecret,
  });
}
