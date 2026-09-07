import {getOrCreateCurrentAccount} from "@/lib/auth/current-account";
import {requireChatGPTUser} from "@/app/chatgpt-auth";
import ReplayUploads from "@/components/narma/replay-uploads";
export const dynamic="force-dynamic";
export const metadata={title:"Реплеи Dota 2 — NARMA VISION"};
export default async function ReplaysPage(){const user=await requireChatGPTUser("/replays");await getOrCreateCurrentAccount(user);return <ReplayUploads/>;}
