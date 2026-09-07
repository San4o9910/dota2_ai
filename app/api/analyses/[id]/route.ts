import { getChatGPTUser } from "@/app/chatgpt-auth";
import { ANALYSIS_ID_PATTERN } from "@/lib/analyses/contracts";
import { AnalysisRouteError, analysisNotFound } from "@/lib/analyses/errors";
import { analysisErrorResponse } from "@/lib/analyses/http";
import { getAnalysisRuntime } from "@/lib/analyses/runtime";
import { D1AnalysisStore } from "@/lib/analyses/store";
import { getCurrentAccount } from "@/lib/auth/current-account";
import { isSameOriginRequest } from "@/lib/security/same-origin";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const requestId = crypto.randomUUID();
  try {
    const user = await getChatGPTUser();
    if (!user) {
      throw new AnalysisRouteError("AUTH_REQUIRED", "Сначала войдите в аккаунт.", 401, false);
    }
    const { id } = await context.params;
    if (!ANALYSIS_ID_PATTERN.test(id)) throw analysisNotFound();
    const runtime = getAnalysisRuntime();
    if (!runtime.db) throw new Error("D1 binding is unavailable");
    const account = await getCurrentAccount(user);
    if (!account || account.status !== "active" || account.deletedAt) throw analysisNotFound();
    const detail = await new D1AnalysisStore(runtime.db).getOwned(account.id, id);
    if (!detail) throw analysisNotFound();
    return Response.json(detail, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return analysisErrorResponse(error, requestId);
  }
}

export async function DELETE(
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
    if (!runtime.db) throw new Error("D1 binding is unavailable");
    const account = await getCurrentAccount(user);
    if (!account || account.status !== "active" || account.deletedAt) throw analysisNotFound();
    const result = await new D1AnalysisStore(runtime.db).cancelOwned(account.id, id);
    if (!result) throw analysisNotFound();
    return Response.json(
      { ...result.detail, cancelOutcome: result.outcome },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    return analysisErrorResponse(error, requestId);
  }
}
