import {getOrCreateCurrentAccount} from "@/lib/auth/current-account";
import type { Metadata } from "next";

import { requireChatGPTUser } from "@/app/chatgpt-auth";
import AnalysisWorkspace from "@/components/narma/analysis-workspace";
import { getAnalysisRuntime } from "@/lib/analyses/runtime";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Мои разборы",
  description: "Защищённая история полных разборов матчей Dota 2.",
};

export default async function AnalysesPage({searchParams}: {searchParams: Promise<{match?: string; replay?: string}>}) {
  const user = await requireChatGPTUser("/analyses");
  await getOrCreateCurrentAccount(user);
  const {match: requestedMatch, replay} = await searchParams;
  const runtime = getAnalysisRuntime();
  return (
    <AnalysisWorkspace
      initialMatchId={typeof requestedMatch === "string" && /^[1-9]\d{7,11}$/.test(requestedMatch) ? requestedMatch : ""}
      initialReplayId={typeof replay === "string" && /^[0-9a-f-]{36}$/i.test(replay) ? replay : ""}
      acceptingJobs={runtime.acceptingJobs && runtime.db !== null}
      fulfillmentReady={runtime.fulfillmentReady && runtime.db !== null}
    />
  );
}
