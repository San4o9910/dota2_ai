export function isSameOriginRequest(request: Request): boolean {
  const origin = request.headers.get("Origin");
  if (!origin) return false;

  try {
    return new URL(origin).origin === new URL(request.url).origin;
  } catch {
    return false;
  }
}

export function sameOriginError() {
  return Response.json(
    { error: "Запрос отклонён: откройте действие из NARMA VISION." },
    { status: 403, headers: { "Cache-Control": "no-store" } },
  );
}
