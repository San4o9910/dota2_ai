import type { Metadata } from "next";

import {
  chatGPTSignInPath,
  chatGPTSignOutPath,
  getChatGPTUser,
} from "@/app/chatgpt-auth";
import PricingPage from "@/components/narma/pricing-page";
import { paymentsEnabled } from "@/lib/payments/runtime";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Тарифы",
  description: "Тарифы NARMA VISION и текущий статус оплаты.",
};

export default async function PlansPage() {
  const user = await getChatGPTUser();
  return (
    <PricingPage
      viewer={user ? { displayName: user.displayName, email: user.email } : null}
      signInHref={chatGPTSignInPath("/pricing")}
      signOutHref={chatGPTSignOutPath("/pricing")}
      checkoutEnabled={paymentsEnabled()}
    />
  );
}
