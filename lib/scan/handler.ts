import { AnalysisError } from "@/lib/analysis/errors";
import { ScanRequestSchema } from "@/lib/scan/contracts";
import { ScanRouteError, scanUnavailable, type ScanErrorEnvelope } from "@/lib/scan/errors";
import { hashRateLimitIdentity, normalizeConnectingIp } from "@/lib/scan/privacy";
import { runScan, type ScanServiceDependencies } from "@/lib/scan/service";
import {
  scanRateWindowStart,
  type ScanRateLimiter,
} from "@/lib/scan/storage";
import { BoundedJsonError, readBoundedJson } from "@/lib/security/bounded-json";
import { isSameOriginRequest } from "@/lib/security/same-origin";
import { AnalysisRouteError } from "@/lib/analyses/errors";
import type { PlayerMatchRequest, PlayerTarget } from "@/lib/dota/player-identity";

export const MAX_SCAN_REQUEST_BYTES = 4 * 1024;

export type ScanHandlerDependencies = ScanServiceDependencies & {
  rateLimiter: ScanRateLimiter;
  rateLimitSecret: string;
  now?: () => number;
  requestId?: () => string;
  resolveTarget: (input:PlayerMatchRequest) => Promise<PlayerTarget>;
};

function response(
  body: unknown,
  status = 200,
  retryAfterSeconds?: number,
): Response {
  const headers = new Headers({ "Cache-Control": "no-store" });
  if (retryAfterSeconds !== undefined) headers.set("Retry-After", String(retryAfterSeconds));
  return Response.json(body, { status, headers });
}

function routeErrorFromBody(error: unknown): ScanRouteError {
  if (error instanceof BoundedJsonError) {
    if (error.code === "too_large") {
      return new ScanRouteError(
        "REQUEST_TOO_LARGE",
        "Запрос NARMA Scan превышает допустимый размер.",
        413,
        false,
      );
    }
    if (error.code === "content_type") {
      return new ScanRouteError(
        "INVALID_CONTENT_TYPE",
        "NARMA Scan принимает только JSON.",
        415,
        false,
      );
    }
  }
  return new ScanRouteError(
    "INVALID_REQUEST_BODY",
    "Проверьте Match ID и выбранного игрока.",
    400,
    false,
    undefined,
    { cause: error },
  );
}

function safeAnalysisStatus(error: AnalysisError): number {
  if (error.code === "OPENDOTA_MATCH_NOT_FOUND") return 404;
  if (error.code === "UPSTREAM_PAYLOAD_TOO_LARGE") return 413;
  if (error.dependency) return 503;
  return error.httpStatus;
}

function errorResponse(error: unknown, requestId: string): Response {
  const safeError = error instanceof ScanRouteError || error instanceof AnalysisError || error instanceof AnalysisRouteError
    ? error
    : scanUnavailable(error);
  const status = safeError instanceof AnalysisError
    ? safeAnalysisStatus(safeError)
    : safeError.httpStatus;
  const envelope: ScanErrorEnvelope = {
    error: {
      code: safeError.code,
      message: safeError.message,
      retryable: safeError.retryable,
      requestId,
    },
  };
  return response(envelope, status, safeError.retryAfterSeconds);
}

export async function handleScanPost(
  request: Request,
  dependencies: ScanHandlerDependencies,
): Promise<Response> {
  const requestId = dependencies.requestId?.() ?? crypto.randomUUID();
  try {
    if (!isSameOriginRequest(request)) {
      throw new ScanRouteError(
        "SAME_ORIGIN_REQUIRED",
        "Запрос отклонён: откройте NARMA Scan на странице приложения.",
        403,
        false,
      );
    }

    const contentType = request.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase();
    if (contentType !== "application/json") throw routeErrorFromBody(new BoundedJsonError("content_type"));

    const connectingIp = normalizeConnectingIp(request.headers.get("CF-Connecting-IP"));
    if (!connectingIp) throw scanUnavailable();
    const nowMs = (dependencies.now ?? Date.now)();
    const keyHash = await hashRateLimitIdentity(
      dependencies.rateLimitSecret,
      connectingIp,
      scanRateWindowStart(nowMs),
    );
    const rateLimit = await dependencies.rateLimiter.take(keyHash, nowMs);
    if (!rateLimit.allowed) {
      throw new ScanRouteError(
        "SCAN_RATE_LIMITED",
        "Лимит бесплатных Scan исчерпан. Повторите позже.",
        429,
        true,
        rateLimit.retryAfterSeconds,
      );
    }

    let raw: unknown;
    try {
      raw = await readBoundedJson(request, MAX_SCAN_REQUEST_BYTES);
    } catch (error) {
      throw routeErrorFromBody(error);
    }
    const parsed = ScanRequestSchema.safeParse(raw);
    if (!parsed.success) throw routeErrorFromBody(parsed.error);

    const target = await dependencies.resolveTarget(parsed.data);
    const result = await runScan({matchId:parsed.data.matchId,playerSlot:target.playerSlot}, {
      cache: dependencies.cache,
      fetch: dependencies.fetch,
      signal: request.signal,
    });
    return response(result);
  } catch (error) {
    return errorResponse(error, requestId);
  }
}

export function scanDisabledResponse(
  request: Request,
  requestId = crypto.randomUUID(),
): Response {
  if (!isSameOriginRequest(request)) {
    return errorResponse(new ScanRouteError(
      "SAME_ORIGIN_REQUIRED",
      "Запрос отклонён: откройте NARMA Scan на странице приложения.",
      403,
      false,
    ), requestId);
  }
  return errorResponse(scanUnavailable(), requestId);
}
