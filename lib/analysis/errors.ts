export type AnalysisErrorCode =
  | "ANALYSIS_CANCELLED"
  | "INVALID_MATCH_ID"
  | "INVALID_PLAYER_SLOT"
  | "SCAN_PREVIEW_UNAVAILABLE"
  | "OPENDOTA_MATCH_NOT_FOUND"
  | "OPENDOTA_MATCH_NOT_PARSED"
  | "OPENDOTA_RATE_LIMITED"
  | "OPENDOTA_UNAVAILABLE"
  | "OPENDOTA_INVALID_RESPONSE"
  | "OPENAI_CONFIGURATION_ERROR"
  | "OPENAI_RATE_LIMITED"
  | "OPENAI_UNAVAILABLE"
  | "OPENAI_INVALID_RESPONSE"
  | "OPENAI_INCOMPLETE"
  | "OPENAI_REFUSAL"
  | "OPENAI_REPORT_UNGROUNDED"
  | "UPSTREAM_PAYLOAD_TOO_LARGE";

type AnalysisErrorOptions = {
  cause?: unknown;
  dependency?: "opendota" | "openai";
  httpStatus: number;
  retryable: boolean;
  retryAfterSeconds?: number;
};

/**
 * A safe, typed failure that can cross the runtime/API boundary. The message is
 * deliberately suitable for end users; provider response bodies and secrets
 * must never be copied into it.
 */
export class AnalysisError extends Error {
  readonly code: AnalysisErrorCode;
  readonly dependency?: "opendota" | "openai";
  readonly httpStatus: number;
  readonly retryable: boolean;
  readonly retryAfterSeconds?: number;

  constructor(code: AnalysisErrorCode, message: string, options: AnalysisErrorOptions) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = "AnalysisError";
    this.code = code;
    this.dependency = options.dependency;
    this.httpStatus = options.httpStatus;
    this.retryable = options.retryable;
    this.retryAfterSeconds = options.retryAfterSeconds;
  }
}

export class AnalysisPublicError extends AnalysisError {
  constructor(
    code: AnalysisErrorCode,
    message: string,
    options: Omit<AnalysisErrorOptions, "dependency">,
  ) {
    super(code, message, options);
    this.name = "AnalysisPublicError";
  }
}

export class AnalysisDependencyError extends AnalysisError {
  constructor(
    dependency: "opendota" | "openai",
    code: AnalysisErrorCode,
    message: string,
    options: Omit<AnalysisErrorOptions, "dependency">,
  ) {
    super(code, message, { ...options, dependency });
    this.name = "AnalysisDependencyError";
  }
}

export type AnalysisErrorEnvelope = {
  error: {
    code: AnalysisErrorCode;
    message: string;
    retryable: boolean;
    requestId: string;
  };
};

export function toAnalysisErrorEnvelope(
  error: AnalysisError,
  requestId: string,
): AnalysisErrorEnvelope {
  return {
    error: {
      code: error.code,
      message: error.message,
      retryable: error.retryable,
      requestId,
    },
  };
}

export function analysisCancelled(cause?: unknown): AnalysisPublicError {
  return new AnalysisPublicError(
    "ANALYSIS_CANCELLED",
    "Операция анализа была отменена.",
    { cause, httpStatus: 503, retryable: true },
  );
}

export function parseRetryAfterSeconds(value: string | null, now = Date.now()): number | undefined {
  if (!value) return undefined;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.min(3600, Math.ceil(seconds));

  const date = Date.parse(value);
  if (!Number.isFinite(date)) return undefined;
  return Math.min(3600, Math.max(0, Math.ceil((date - now) / 1000)));
}
