import type { Metadata } from "next";

import {
  chatGPTSignOutPath,
  requireChatGPTUser,
} from "@/app/chatgpt-auth";
import AccountDashboard from "@/components/narma/account-dashboard";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Аккаунт и настройки",
  description: "Аккаунт, лимиты и настройки NARMA VISION.",
};

export default async function AccountPage() {
  const user = await requireChatGPTUser("/account");
  return (
    <AccountDashboard
      displayName={user.displayName}
      email={user.email}
      signOutHref={chatGPTSignOutPath("/")}
    />
  );
}
