import { and, eq, sql } from "drizzle-orm";

import type { ChatGPTUser } from "@/app/chatgpt-auth";
import { getDb } from "@/db";
import { authIdentities, entitlementLedger, users } from "@/db/schema";
import { freeTrialLedgerEntries } from "@/lib/billing/ledger";

const PROVIDER = "chatgpt";

export type CurrentAccount = {
  id: string;
  displayName: string;
  status: string;
  deletedAt: string | null;
  planCode: string;
  analysisCredits: number;
  coachQuestionsRemaining: number;
  planExpiresAt: string | null;
};

async function findBySubject(providerSubject: string): Promise<CurrentAccount | null> {
  const db = getDb();
  await db.run(sql`
    UPDATE users
    SET subscription_analysis_credits = 0,
        subscription_coach_questions_remaining = 0,
        plan_code = 'free_trial',
        plan_expires_at = NULL,
        updated_at = CURRENT_TIMESTAMP
    WHERE plan_code = 'coach_30_days'
      AND plan_expires_at IS NOT NULL
      AND plan_expires_at <= CURRENT_TIMESTAMP
      AND id IN (
        SELECT user_id
        FROM auth_identities
        WHERE provider = ${PROVIDER}
          AND provider_subject = ${providerSubject}
      )
  `);
  const [row] = await db
    .select({
      id: users.id,
      displayName: users.displayName,
      status: users.status,
      deletedAt: users.deletedAt,
      planCode: users.planCode,
      analysisCredits: sql<number>`COALESCE((
        SELECT SUM(delta)
        FROM entitlement_ledger
        WHERE user_id = ${users.id}
          AND resource = 'analysis'
          AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
      ), 0)`,
      coachQuestionsRemaining: sql<number>`COALESCE((
        SELECT SUM(delta)
        FROM entitlement_ledger
        WHERE user_id = ${users.id}
          AND resource = 'coach_question'
          AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
      ), 0)`,
      planExpiresAt: users.planExpiresAt,
    })
    .from(authIdentities)
    .innerJoin(users, eq(authIdentities.userId, users.id))
    .where(
      and(
        eq(authIdentities.provider, PROVIDER),
        eq(authIdentities.providerSubject, providerSubject),
      ),
    )
    .limit(1);
  return row ?? null;
}

export async function getCurrentAccount(user: ChatGPTUser) {
  return findBySubject(user.id.slice(0, 512));
}

export async function getOrCreateCurrentAccount(user: ChatGPTUser) {
  const providerSubject = user.id.slice(0, 512);
  const displayName = user.displayName.slice(0, 160);
  const email = user.email.slice(0, 320);
  const existing = await findBySubject(providerSubject);
  const db = getDb();

  if (existing) {
    if (existing.status === "deleted" || existing.deletedAt) return existing;
    await db.batch([
      db
        .update(authIdentities)
        .set({ email, lastSeenAt: sql`CURRENT_TIMESTAMP` })
        .where(
          and(
            eq(authIdentities.provider, PROVIDER),
            eq(authIdentities.providerSubject, providerSubject),
          ),
        ),
      db
        .update(users)
        .set({ displayName, updatedAt: sql`CURRENT_TIMESTAMP` })
        .where(eq(users.id, existing.id)),
    ]);
    return { ...existing, displayName };
  }

  const userId = crypto.randomUUID();
  try {
    const initialEntitlements = freeTrialLedgerEntries(userId);
    await db.batch([
      db.insert(users).values({ id: userId, displayName }),
      db.insert(authIdentities).values({
        id: crypto.randomUUID(),
        userId,
        provider: PROVIDER,
        providerSubject,
        email,
      }),
      db.insert(entitlementLedger).values(initialEntitlements),
    ]);
  } catch (error) {
    // Two first requests can race. D1 rolls the failed batch back, so the
    // request that lost the unique identity race can safely reuse the winner.
    const concurrent = await findBySubject(providerSubject);
    if (concurrent) return concurrent;
    throw error;
  }

  const created = await findBySubject(providerSubject);
  if (!created) throw new Error("Account was not created");
  return created;
}
