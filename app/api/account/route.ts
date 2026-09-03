import { getChatGPTUser } from "@/app/chatgpt-auth";
import {
  getCurrentAccount,
  getOrCreateCurrentAccount,
} from "@/lib/auth/current-account";
import { isSameOriginRequest, sameOriginError } from "@/lib/security/same-origin";

export const dynamic = "force-dynamic";

function unavailable(error: unknown) {
  const message = error instanceof Error ? error.message : "Unknown database error";
  const isBindingMissing = message.includes("D1 binding `DB` is unavailable");
  return Response.json(
    {
      error: isBindingMissing
        ? "Профиль войдёт в рабочий режим после подключения защищённой базы."
        : "Не удалось открыть профиль. Попробуйте ещё раз.",
    },
    {
      status: isBindingMissing ? 503 : 500,
      headers: { "Cache-Control": "no-store" },
    },
  );
}

function publicAccount(account: Awaited<ReturnType<typeof getCurrentAccount>>) {
  if (!account) return null;
  return {
    displayName: account.displayName,
    status: account.status,
    planCode: account.planCode,
    analysisCredits: account.analysisCredits,
    coachQuestionsRemaining: account.coachQuestionsRemaining,
    planExpiresAt: account.planExpiresAt,
  };
}

export async function GET() {
  const user = await getChatGPTUser();
  if (!user) {
    return Response.json(
      { error: "Сначала войдите в аккаунт." },
      { status: 401, headers: { "Cache-Control": "no-store" } },
    );
  }

  try {
    const account = publicAccount(await getCurrentAccount(user));
    return Response.json(
      { account },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    return unavailable(error);
  }
}

export async function POST(request: Request) {
  if (!isSameOriginRequest(request)) return sameOriginError();

  const user = await getChatGPTUser();
  if (!user) {
    return Response.json(
      { error: "Сначала войдите в аккаунт." },
      { status: 401, headers: { "Cache-Control": "no-store" } },
    );
  }

  try {
    const account = publicAccount(await getOrCreateCurrentAccount(user));
    return Response.json(
      { account, createdOrUpdated: true },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    return unavailable(error);
  }
}
