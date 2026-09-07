import {
  chatGPTSignInPath,
  chatGPTSignOutPath,
  getChatGPTUser,
} from "@/app/chatgpt-auth";
import NarmaAnalysis from "@/components/narma/narma-analysis";
import { scanRuntimeEnabled } from "@/lib/scan/runtime";

export const dynamic = "force-dynamic";

export default async function Home() {
  const user = await getChatGPTUser();
  return (
    <NarmaAnalysis
      viewer={user ? { displayName: user.displayName, email: user.email } : null}
      signInHref={chatGPTSignInPath("/")}
      signOutHref={chatGPTSignOutPath("/")}
      scanEnabled={scanRuntimeEnabled()}
    />
  );
}
