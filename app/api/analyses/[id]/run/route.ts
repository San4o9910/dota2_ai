import {D1PlayerBindingStore} from "@/lib/dota/player-binding";
import { after } from "next/server";
import { getChatGPTUser } from "@/app/chatgpt-auth";
import { ANALYSIS_ID_PATTERN } from "@/lib/analyses/contracts";
import {
  AnalysisRouteError,
  analysisNotFound,
  fulfillmentDisabled,
} from "@/lib/analyses/errors";
import { analysisErrorResponse } from "@/lib/analyses/http";
import { getAnalysisRuntime } from "@/lib/analyses/runtime";
import { runOwnedAnalysis } from "@/lib/analyses/service";
import { D1AnalysisStore } from "@/lib/analyses/store";
import { getCurrentAccount } from "@/lib/auth/current-account";
import { D1ScanMatchCache } from "@/lib/scan/storage";
import { isSameOriginRequest } from "@/lib/security/same-origin";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const requestId = crypto.randomUUID();
  try {
    if (!isSameOriginRequest(request)) {
      throw new AnalysisRouteError(
        "SAME_ORIGIN_REQUIRED",
        "Запрос отклонён: откройте анализ на странице приложения.",
        403,
        false,
      );
    }
    const user = await getChatGPTUser();
    if (!user) {
      throw new AnalysisRouteError("AUTH_REQUIRED", "Сначала войдите в аккаунт.", 401, false);
    }
    const { id } = await context.params;
    if (!ANALYSIS_ID_PATTERN.test(id)) throw analysisNotFound();
    const runtime = getAnalysisRuntime();
    if (
      !runtime.fulfillmentReady
      || !runtime.db
      || !runtime.apiKey
      || !runtime.model
    ) throw fulfillmentDisabled();
    const account = await getCurrentAccount(user);
    if (!account || account.status !== "active" || account.deletedAt) throw analysisNotFound();

    const store = new D1AnalysisStore(runtime.db);
    const work = runOwnedAnalysis(account.id, id, {
      store,
      cache: new D1ScanMatchCache(runtime.db),
      apiKey: runtime.apiKey,
      model: runtime.model,
      allowedModels: runtime.allowedModels,
      authorizeTarget:(userId,matchId,slot)=>new D1PlayerBindingStore(runtime.db!).assertTarget(userId,matchId,slot),
      signal: AbortSignal.timeout(25_000),
    });
    after(work);
    const result = await work;
    if (result.outcome === "not_found" || !result.detail) throw analysisNotFound();
    const status = ["ready", "failed", "canceled"].includes(result.detail.job.state)
      ? 200
      : 202;
    const headers = new Headers({ "Cache-Control": "no-store" });
    if (result.retryAfterSeconds !== undefined) {
      headers.set("Retry-After", String(result.retryAfterSeconds));
    }
    return Response.json(
      { ...result.detail, runOutcome: result.outcome },
      { status, headers },
    );
  } catch (error) {
    return analysisErrorResponse(error, requestId);
  }
}
