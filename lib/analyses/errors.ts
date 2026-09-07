export type AnalysisRouteErrorCode =
  | `DOTA_${string}`
  | "ANALYSIS_RATE_LIMITED"
  | "ACCOUNT_INACTIVE"
  | "ANALYSIS_BUSY"
  | "ANALYSIS_DISABLED"
  | "ANALYSIS_FULFILLMENT_DISABLED"
  | "ANALYSIS_NOT_FOUND"
  | "AUTH_REQUIRED"
  | "ENTITLEMENT_REQUIRED"
  | "IDEMPOTENCY_CONFLICT"
  | "INVALID_CONTENT_TYPE"
  | "INVALID_CURSOR"
  | "INVALID_IDEMPOTENCY_KEY"
  | "INVALID_REQUEST_BODY"
  | "REQUEST_TOO_LARGE"
  | "SAME_ORIGIN_REQUIRED"
  | "STORAGE_UNAVAILABLE";

export class AnalysisRouteError extends Error {
  readonly code: AnalysisRouteErrorCode;
  readonly httpStatus: number;
  readonly retryable: boolean;
  readonly retryAfterSeconds?: number;

  constructor(
    code: AnalysisRouteErrorCode,
    message: string,
    httpStatus: number,
    retryable: boolean,
    options: { cause?: unknown; retryAfterSeconds?: number } = {},
  ) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = "AnalysisRouteError";
    this.code = code;
    this.httpStatus = httpStatus;
    this.retryable = retryable;
    this.retryAfterSeconds = options.retryAfterSeconds;
  }
}

export function storageUnavailable(cause?: unknown) {
  return new AnalysisRouteError(
    "STORAGE_UNAVAILABLE",
    "Хранилище анализов временно недоступно.",
    503,
    true,
    { cause },
  );
}

export function analysisNotFound() {
  return new AnalysisRouteError(
    "ANALYSIS_NOT_FOUND",
    "Анализ не найден.",
    404,
    false,
  );
}

export function analysisDisabled() {
  return new AnalysisRouteError(
    "ANALYSIS_DISABLED",
    "Создание полных анализов пока выключено.",
    503,
    false,
  );
}

export function fulfillmentDisabled() {
  return new AnalysisRouteError(
    "ANALYSIS_FULFILLMENT_DISABLED",
    "Генерация полного отчёта пока выключена.",
    503,
    false,
  );
}

export type AnalysisRouteErrorEnvelope = {
  error: {
    code: string;
    message: string;
    retryable: boolean;
    requestId: string;
  };
};

export function errorEnvelope(
  error: { code: string; message: string; retryable: boolean },
  requestId: string,
): AnalysisRouteErrorEnvelope {
  return {
    error: {
      code: error.code,
      message: error.message,
      retryable: error.retryable,
      requestId,
    },
  };
}
