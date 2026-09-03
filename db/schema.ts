import { sql } from "drizzle-orm";
import {
  index,
  integer,
  sqliteTable,
  text,
  uniqueIndex,
} from "drizzle-orm/sqlite-core";

export const users = sqliteTable("users", {
  id: text("id").primaryKey(),
  displayName: text("display_name").notNull(),
  status: text("status").notNull().default("active"),
  planCode: text("plan_code").notNull().default("free_trial"),
  subscriptionAnalysisCredits: integer("subscription_analysis_credits").notNull().default(0),
  subscriptionCoachQuestionsRemaining: integer("subscription_coach_questions_remaining").notNull().default(0),
  analysisCredits: integer("analysis_credits").notNull().default(1),
  coachQuestionsRemaining: integer("coach_questions_remaining").notNull().default(5),
  planExpiresAt: text("plan_expires_at"),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const authIdentities = sqliteTable(
  "auth_identities",
  {
    id: text("id").primaryKey(),
    userId: text("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    provider: text("provider").notNull(),
    providerSubject: text("provider_subject").notNull(),
    email: text("email").notNull(),
    createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
    lastSeenAt: text("last_seen_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  },
  (table) => [
    uniqueIndex("auth_provider_subject_unique").on(
      table.provider,
      table.providerSubject,
    ),
  ],
);

export const orders = sqliteTable(
  "orders",
  {
    id: text("id").primaryKey(),
    userId: text("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    productCode: text("product_code").notNull(),
    checkoutAttemptId: text("checkout_attempt_id").notNull().unique(),
    matchId: text("match_id"),
    amountKopecks: integer("amount_kopecks").notNull(),
    status: text("status").notNull().default("created"),
    yookassaPaymentId: text("yookassa_payment_id").unique(),
    creditedAt: text("credited_at"),
    createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
    updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  },
  (table) => [
    index("orders_user_created_idx").on(table.userId, table.createdAt),
    uniqueIndex("orders_one_open_coach_per_user")
      .on(table.userId)
      .where(sql`
        product_code = 'coach_30_days'
        AND status IN ('created', 'pending', 'waiting_for_capture')
      `),
  ],
);
