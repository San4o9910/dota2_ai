import { AnalysisDependencyError } from "@/lib/analysis/errors";

export type DependencyName = "opendota" | "openai";

export type BoundedJsonOptions = {
  dependency: DependencyName;
  maxBytes: number;
  signal?: AbortSignal;
};

export type TimeoutContext = {
  cleanup(): void;
  signal: AbortSignal;
  timedOut(): boolean;
};

export function createTimeoutContext(timeoutMs: number, parentSignal?: AbortSignal): TimeoutContext {
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 120_000) {
    throw new RangeError("timeoutMs must be between 1 and 120000");
  }

  const controller = new AbortController();
  let timeoutReached = false;
  const onParentAbort = () => controller.abort(parentSignal?.reason);
  if (parentSignal?.aborted) onParentAbort();
  else parentSignal?.addEventListener("abort", onParentAbort, { once: true });

  const timer = setTimeout(() => {
    timeoutReached = true;
    controller.abort(new DOMException("Request timed out", "TimeoutError"));
  }, timeoutMs);

  return {
    signal: controller.signal,
    timedOut: () => timeoutReached,
    cleanup: () => {
      clearTimeout(timer);
      parentSignal?.removeEventListener("abort", onParentAbort);
    },
  };
}

export async function cancelResponseBody(response: Response): Promise<void> {
  try {
    void response.body?.cancel().catch(() => undefined);
  } catch {
    // Cancellation is best-effort. Provider bodies are intentionally not read.
  }
}

function contentTypeIsJson(value: string | null) {
  if (!value) return false;
  const mediaType = value.split(";", 1)[0].trim().toLowerCase();
  return mediaType === "application/json" || mediaType.endsWith("+json");
}

export async function readBoundedJson(response: Response, options: BoundedJsonOptions): Promise<unknown> {
  const { dependency, maxBytes, signal } = options;
  if (!Number.isSafeInteger(maxBytes) || maxBytes < 1) throw new RangeError("maxBytes must be positive");

  if (!contentTypeIsJson(response.headers.get("content-type"))) {
    await cancelResponseBody(response);
    throw new AnalysisDependencyError(
      dependency,
      dependency === "opendota" ? "OPENDOTA_INVALID_RESPONSE" : "OPENAI_INVALID_RESPONSE",
      "Внешний сервис вернул ответ в неподдерживаемом формате.",
      { httpStatus: 503, retryable: false },
    );
  }

  const declaredLength = response.headers.get("content-length");
  if (declaredLength !== null) {
    const length = Number(declaredLength);
    if (Number.isFinite(length) && length > maxBytes) {
      void response.body?.cancel().catch(() => undefined);
      throw new AnalysisDependencyError(
        dependency,
        "UPSTREAM_PAYLOAD_TOO_LARGE",
        "Ответ внешнего сервиса превышает безопасный размер.",
        { httpStatus: 413, retryable: false },
      );
    }
  }

  const reader = response.body?.getReader();
  if (!reader) {
    await cancelResponseBody(response);
    throw new AnalysisDependencyError(
      dependency,
      dependency === "opendota" ? "OPENDOTA_INVALID_RESPONSE" : "OPENAI_INVALID_RESPONSE",
      "Внешний сервис вернул пустой ответ.",
      { httpStatus: 503, retryable: false },
    );
  }

  const decoder = new TextDecoder();
  let bytes = 0;
  let text = "";
  try {
    while (true) {
      if (signal?.aborted) {
        void reader.cancel(signal.reason).catch(() => undefined);
        throw signal.reason ?? new DOMException("Request aborted", "AbortError");
      }
      const read = reader.read();
      const { done, value } = signal
        ? await new Promise<ReadableStreamReadResult<Uint8Array>>((resolve, reject) => {
          let listening = true;
          const cleanup = () => {
            if (!listening) return;
            listening = false;
            signal.removeEventListener("abort", onAbort);
          };
          const onAbort = () => {
            cleanup();
            void reader.cancel(signal.reason).catch(() => undefined);
            reject(signal.reason ?? new DOMException("Request aborted", "AbortError"));
          };
          signal.addEventListener("abort", onAbort, { once: true });
          if (signal.aborted) onAbort();
          read.then(
            (result) => { cleanup(); resolve(result); },
            (error) => { cleanup(); reject(error); },
          );
        })
        : await read;
      if (done) break;
      bytes += value.byteLength;
      if (bytes > maxBytes) {
        void reader.cancel().catch(() => undefined);
        throw new AnalysisDependencyError(
          dependency,
          "UPSTREAM_PAYLOAD_TOO_LARGE",
          "Ответ внешнего сервиса превышает безопасный размер.",
          { httpStatus: 413, retryable: false },
        );
      }
      text += decoder.decode(value, { stream: true });
    }
    text += decoder.decode();
  } catch (error) {
    if (error instanceof AnalysisDependencyError) throw error;
    throw new AnalysisDependencyError(
      dependency,
      dependency === "opendota" ? "OPENDOTA_INVALID_RESPONSE" : "OPENAI_INVALID_RESPONSE",
      "Не удалось прочитать ответ внешнего сервиса.",
      { cause: error, httpStatus: 503, retryable: true },
    );
  }

  try {
    return JSON.parse(text) as unknown;
  } catch (error) {
    throw new AnalysisDependencyError(
      dependency,
      dependency === "opendota" ? "OPENDOTA_INVALID_RESPONSE" : "OPENAI_INVALID_RESPONSE",
      "Внешний сервис вернул повреждённый JSON.",
      { cause: error, httpStatus: 503, retryable: false },
    );
  }
}
