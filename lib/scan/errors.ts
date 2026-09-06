export type ScanErrorCode =
  | "SAME_ORIGIN_REQUIRED"
  | "SCAN_UNAVAILABLE"
  | "SCAN_RATE_LIMITED"
  | "INVALID_CONTENT_TYPE"
  | "INVALID_REQUEST_BODY"
  | "REQUEST_TOO_LARGE";

export type ScanErrorEnvelope = {
  error: {
    code: ScanErrorCode | import("@/lib/analysis/errors").AnalysisErrorCode | import("@/lib/analyses/errors").AnalysisRouteErrorCode;
    message: string;
    retryable: boolean;
    requestId: string;
  };
};

export class ScanRouteError extends Error {
  constructor(
    readonly code: ScanErrorCode,
    message: string,
    readonly httpStatus: number,
    readonly retryable: boolean,
    readonly retryAfterSeconds?: number,
    options: { cause?: unknown } = {},
  ) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = "ScanRouteError";
  }
}

export function scanUnavailable(cause?: unknown) {
  return new ScanRouteError(
    "SCAN_UNAVAILABLE",
    "NARMA Scan временно недоступен. Попробуйте позже.",
    503,
    true,
    undefined,
    { cause },
  );
}
