import { isJsonContentType } from "@/lib/security/content-type";

export type BoundedJsonErrorCode = "content_type" | "empty" | "too_large" | "invalid_json";

export class BoundedJsonError extends Error {
  constructor(readonly code: BoundedJsonErrorCode) {
    super(code);
    this.name = "BoundedJsonError";
  }
}

export async function readBoundedJson(request: Request, maxBytes: number) {
  if (!Number.isSafeInteger(maxBytes) || maxBytes < 1) {
    throw new TypeError("maxBytes must be a positive safe integer");
  }
  if (!isJsonContentType(request.headers.get("content-type"))) {
    throw new BoundedJsonError("content_type");
  }
  const declaredLength = request.headers.get("content-length");
  if (declaredLength && Number(declaredLength) > maxBytes) {
    throw new BoundedJsonError("too_large");
  }
  const reader = request.body?.getReader();
  if (!reader) throw new BoundedJsonError("empty");

  const chunks: Uint8Array[] = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > maxBytes) {
      await reader.cancel();
      throw new BoundedJsonError("too_large");
    }
    chunks.push(value);
  }
  if (size === 0) throw new BoundedJsonError("empty");

  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    return JSON.parse(new TextDecoder().decode(bytes)) as unknown;
  } catch {
    throw new BoundedJsonError("invalid_json");
  }
}
