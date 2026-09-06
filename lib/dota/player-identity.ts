import { z } from "zod";
import { MATCH_ID_PATTERN, PlayerSlotSchema } from "@/lib/analysis/contracts";
import { AnalysisRouteError } from "@/lib/analyses/errors";

export const NicknameSchema = z.string().trim().min(1).max(128)
  .refine(value => !/[\u0000-\u001f\u007f]/.test(value));
export const PlayerMatchRequestSchema = z.object({
  matchId: z.string().regex(MATCH_ID_PATTERN),
  nickname: NicknameSchema.optional(),
}).strict();
export const ProfileBindingRequestSchema = PlayerMatchRequestSchema.extend({ replayId: z.string().uuid().optional() }).strict();
export type PlayerMatchRequest = z.infer<typeof PlayerMatchRequestSchema>;
export const IdentitySchema = z.object({
  playerSlot: PlayerSlotSchema,
  accountId: z.number().int().min(1).max(4294967294).nullable(),
  nickname: z.string().max(128).nullable(),
  heroId: z.number().int().positive().max(1024),
}).strict();
export const IdentityRosterSchema = z.array(IdentitySchema).length(10).superRefine((rows, ctx) => {
  if (new Set(rows.map(row => row.playerSlot)).size !== 10)
    ctx.addIssue({ code: "custom", message: "Duplicate player slots" });
});
export type PlayerIdentity = z.infer<typeof IdentitySchema>;
export type PlayerTarget = PlayerIdentity & { accountId: number; matchId: string; nickname: string };
export function playerError(code: `DOTA_${string}`, message: string, status = 409) {
  return new AnalysisRouteError(code, message, status, false);
}
export function nicknameKey(value: string) { return value.trim().normalize("NFC").toLowerCase(); }
export function extractIdentityRoster(players: Array<Record<string, unknown>>) {
  return IdentityRosterSchema.parse(players.map(player => ({
    playerSlot: player.player_slot,
    heroId: player.hero_id,
    accountId: typeof player.account_id === "number" && Number.isInteger(player.account_id)
      && player.account_id > 0 && player.account_id < 4294967295 ? player.account_id : null,
    nickname: typeof player.personaname === "string" ? player.personaname.slice(0,128) : null,
  })));
}
export function selectIdentity<T extends { nickname: string | null; accountId: number | null }>(roster: T[], nickname?: string, accountId?: number) {
  const matches = accountId === undefined
    ? roster.filter(player => player.nickname !== null && nicknameKey(player.nickname) === nicknameKey(nickname ?? ""))
    : roster.filter(player => player.accountId === accountId);
  if (matches.length > 1) throw playerError("DOTA_PLAYER_AMBIGUOUS", "В матче несколько игроков с таким ником. Привязка не сохранена.");
  if (matches.length === 0) throw playerError("DOTA_PLAYER_NOT_FOUND", accountId === undefined
    ? "Этот ник не найден в матче. Проверьте написание и Match ID."
    : "Закреплённый игрок не найден в этом матче.", 404);
  const player = matches[0];
  if (player.accountId === null) throw playerError("DOTA_IDENTITY_UNAVAILABLE", "Источник скрывает ID этого игрока. Нужен реплей с доступным профилем.");
  return { ...player, accountId: player.accountId };
}
