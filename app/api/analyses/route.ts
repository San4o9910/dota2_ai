import { getChatGPTUser } from "@/app/chatgpt-auth";
import { AnalysisRouteError, analysisDisabled } from "@/lib/analyses/errors";
import { analysisErrorResponse, handleCreateAnalysis } from "@/lib/analyses/http";
import { getAnalysisRuntime } from "@/lib/analyses/runtime";
import { decodeAnalysisCursor, D1AnalysisStore } from "@/lib/analyses/store";
import { getCurrentAccount, getOrCreateCurrentAccount } from "@/lib/auth/current-account";
import { D1PlayerBindingStore } from "@/lib/dota/player-binding";

export const dynamic = "force-dynamic";

function authRequired() {
  return new AnalysisRouteError(
    "AUTH_REQUIRED",
    "Сначала войдите в аккаунт.",
    401,
    false,
  );
}

export async function POST(request: Request) {
  const requestId = crypto.randomUUID();
  try {
    const user = await getChatGPTUser();
    if (!user) throw authRequired();
    const runtime = getAnalysisRuntime();
    if (!runtime.acceptingJobs) throw analysisDisabled();
    if (!runtime.db) throw new Error("D1 binding is unavailable");
    const account = await getOrCreateCurrentAccount(user);
    return handleCreateAnalysis(request, {
      account,
      store: new D1AnalysisStore(runtime.db),
      acceptingJobs: runtime.acceptingJobs,
      resolveTarget: input => new D1PlayerBindingStore(runtime.db!).resolve(account.id,input,{signal:request.signal}),
      requestId: () => requestId,
    });
  } catch (error) {
    return analysisErrorResponse(error, requestId);
  }
}

export async function GET(request: Request) {
  const requestId = crypto.randomUUID();
  try {
    const user = await getChatGPTUser();
    if (!user) throw authRequired();
    const runtime = getAnalysisRuntime();
    if (!runtime.db) throw new Error("D1 binding is unavailable");
    const account = await getCurrentAccount(user);
    if (!account) {
      return Response.json(
        { jobs: [], nextCursor: null },
        { headers: { "Cache-Control": "no-store" } },
      );
    }
    if (account.status !== "active" || account.deletedAt) {
      throw new AnalysisRouteError(
        "ACCOUNT_INACTIVE",
        "Этот аккаунт не может просматривать анализы.",
        403,
        false,
      );
    }

    const url = new URL(request.url);
    const cursorValue = url.searchParams.get("cursor");
    const cursor = cursorValue ? decodeAnalysisCursor(cursorValue) : null;
    if (cursorValue && !cursor) {
      throw new AnalysisRouteError(
        "INVALID_CURSOR",
        "Курсор истории анализов некорректен.",
        400,
        false,
      );
    }
    const limitValue = url.searchParams.get("limit");
    const limit = limitValue === null ? undefined : Number(limitValue);
    if (limit !== undefined && (!Number.isInteger(limit) || limit < 1 || limit > 50)) {
      throw new AnalysisRouteError(
        "INVALID_CURSOR",
        "Размер страницы истории должен быть от одного до пятидесяти.",
        400,
        false,
      );
    }
    const history = await new D1AnalysisStore(runtime.db).listOwned(account.id, { cursor, limit });
    return Response.json(history, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return analysisErrorResponse(error, requestId);
  }
}
