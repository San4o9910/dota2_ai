import {
  CreateAnalysisRequestSchema,
  IDEMPOTENCY_KEY_PATTERN,
  type PublicAnalysisJob,
} from "@/lib/analyses/contracts";
import {
  AnalysisRouteError,
  analysisDisabled,
  errorEnvelope,
  storageUnavailable,
} from "@/lib/analyses/errors";
import type { D1AnalysisStore } from "@/lib/analyses/store";
import { BoundedJsonError, readBoundedJson } from "@/lib/security/bounded-json";
import { isSameOriginRequest } from "@/lib/security/same-origin";
import type { PlayerMatchRequest, PlayerTarget } from "@/lib/dota/player-identity";

export const MAX_ANALYSIS_REQUEST_BYTES = 4 * 1024;

export type AnalysisAccount = {
  id: string;
  status: string;
  deletedAt: string | null;
};

function response(body: unknown, status = 200, headers?: HeadersInit) {
  return Response.json(body, {
    status,
    headers: { "Cache-Control": "no-store", ...headers },
  });
}

export function analysisErrorResponse(
  error: unknown,
  requestId = crypto.randomUUID(),
) {
  const safe = error instanceof AnalysisRouteError ? error : storageUnavailable(error);
  const headers = safe.retryAfterSeconds === undefined
    ? undefined
    : { "Retry-After": String(safe.retryAfterSeconds) };
  return response(errorEnvelope(safe, requestId), safe.httpStatus, headers);
}

function bodyError(error: unknown) {
  if (error instanceof BoundedJsonError && error.code === "too_large") {
    return new AnalysisRouteError(
      "REQUEST_TOO_LARGE",
      "Запрос анализа превышает допустимый размер.",
      413,
      false,
    );
  }
  if (error instanceof BoundedJsonError && error.code === "content_type") {
    return new AnalysisRouteError(
      "INVALID_CONTENT_TYPE",
      "API анализов принимает только JSON.",
      415,
      false,
    );
  }
  return new AnalysisRouteError(
    "INVALID_REQUEST_BODY",
    "Проверьте Match ID и выбранного игрока.",
    400,
    false,
    { cause: error },
  );
}

export async function handleCreateAnalysis(
  request: Request,
  dependencies: {
    account: AnalysisAccount;
    store: D1AnalysisStore;
    acceptingJobs: boolean;
    resolveTarget: (input: PlayerMatchRequest) => Promise<PlayerTarget>;
    requestId?: () => string;
  },
) {
  const requestId = dependencies.requestId?.() ?? crypto.randomUUID();
  try {
    if (!isSameOriginRequest(request)) {
      throw new AnalysisRouteError(
        "SAME_ORIGIN_REQUIRED",
        "Запрос отклонён: откройте анализ на странице приложения.",
        403,
        false,
      );
    }
    if (!dependencies.acceptingJobs) throw analysisDisabled();
    if (dependencies.account.status !== "active" || dependencies.account.deletedAt) {
      throw new AnalysisRouteError(
        "ACCOUNT_INACTIVE",
        "Этот аккаунт не может создавать новые анализы.",
        403,
        false,
      );
    }

    const idempotencyKey = request.headers.get("Idempotency-Key") ?? "";
    if (!IDEMPOTENCY_KEY_PATTERN.test(idempotencyKey)) {
      throw new AnalysisRouteError(
        "INVALID_IDEMPOTENCY_KEY",
        "Повторите запрос с корректным ключом идемпотентности.",
        400,
        false,
      );
    }

    let raw: unknown;
    try {
      raw = await readBoundedJson(request, MAX_ANALYSIS_REQUEST_BYTES);
    } catch (error) {
      throw bodyError(error);
    }
    const parsed = CreateAnalysisRequestSchema.safeParse(raw);
    if (!parsed.success) throw bodyError(parsed.error);

    const target = await dependencies.resolveTarget(parsed.data);
    const created = await dependencies.store.create({
      userId: dependencies.account.id,
      matchId: parsed.data.matchId,
      playerSlot: target.playerSlot,
      idempotencyKey,
    });
    if (created.outcome === "idempotency_conflict") {
      throw new AnalysisRouteError(
        "IDEMPOTENCY_CONFLICT",
        "Этот ключ уже использован для другого анализа.",
        409,
        false,
      );
    }
    if (created.outcome === "rate_limited") throw new AnalysisRouteError("ANALYSIS_RATE_LIMITED","Дождитесь текущего разбора. После ошибки повтор этого матча доступен через пятнадцать минут.",429,true,{retryAfterSeconds:900});
    if (created.outcome === "insufficient_entitlement") {
      throw new AnalysisRouteError(
        "ENTITLEMENT_REQUIRED",
        "Нет доступного полного разбора.",
        402,
        false,
      );
    }

    return response(
      { job: created.job, replayed: created.outcome === "replayed" },
      created.outcome === "created" ? 201 : 200,
      { Location: `/api/analyses/${created.job.id}` },
    );
  } catch (error) {
    return analysisErrorResponse(error, requestId);
  }
}

export function analysisJobResponse(job: PublicAnalysisJob, replayed = false) {
  return response({ job, replayed });
}
