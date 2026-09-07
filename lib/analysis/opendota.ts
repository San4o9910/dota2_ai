import { z } from "zod";
import { MATCH_ID_PATTERN, PlayerSlotSchema } from "@/lib/analysis/contracts";
import { AnalysisPublicError } from "@/lib/analysis/errors";

// Historical payload validation is retained for stored reports and local replay
// adapters. This module has no remote transport and cannot contact a provider.
const CANONICAL_PLAYER_SLOTS = [0, 1, 2, 3, 4, 128, 129, 130, 131, 132] as const;

const nullableInteger = z.number().int().safe().finite().nullable().optional();
const nullableNonNegativeInteger = z.number().int().nonnegative().safe().finite().nullable().optional();

const OpenDotaPlayerSchema = z.object({
  player_slot: PlayerSlotSchema,
  hero_id: z.number().int().positive().max(1024),
  lane_role: z.number().int().min(0).max(5).nullable().optional(),
  is_roaming: z.boolean().nullable().optional(),
  kills: nullableNonNegativeInteger,
  deaths: nullableNonNegativeInteger,
  assists: nullableNonNegativeInteger,
  last_hits: nullableNonNegativeInteger,
  denies: nullableNonNegativeInteger,
  gold_per_min: nullableNonNegativeInteger,
  xp_per_min: nullableNonNegativeInteger,
  level: z.number().int().min(0).max(100).nullable().optional(),
  net_worth: nullableNonNegativeInteger,
  obs_placed: nullableNonNegativeInteger,
  sen_placed: nullableNonNegativeInteger,
  item_0: nullableNonNegativeInteger,
  item_1: nullableNonNegativeInteger,
  item_2: nullableNonNegativeInteger,
  item_3: nullableNonNegativeInteger,
  item_4: nullableNonNegativeInteger,
  item_5: nullableNonNegativeInteger,
}).passthrough();

const OpenDotaObjectiveSchema = z.object({
  time: z.number().int().min(-600).max(43200),
  type: z.string().max(80),
  team: z.number().int().safe().nullable().optional(),
  slot: z.number().int().safe().nullable().optional(),
  player_slot: z.number().int().safe().nullable().optional(),
  key: z.union([z.string().max(256), z.number().safe()]).nullable().optional(),
}).passthrough();

const OpenDotaFightPlayerSchema = z.object({
  deaths: nullableNonNegativeInteger,
  buybacks: nullableNonNegativeInteger,
  gold_delta: nullableInteger,
  xp_delta: nullableInteger,
  damage: nullableNonNegativeInteger,
}).passthrough();

const OpenDotaTeamfightSchema = z.object({
  start: z.number().int().min(-600).max(43200),
  end: z.number().int().min(-600).max(43200),
  players: z.array(OpenDotaFightPlayerSchema).length(10),
}).passthrough().refine((fight) => fight.end >= fight.start, "teamfight end must not precede start");

export const OpenDotaMatchSchema = z.object({
  match_id: z.union([z.string().regex(MATCH_ID_PATTERN), z.number().int().positive().safe()]),
  version: z.number().int().positive().safe().nullable().optional(),
  patch: z.union([z.string().max(32), z.number().nonnegative().safe().finite()]).nullable().optional(),
  start_time: nullableNonNegativeInteger,
  duration: z.number().int().positive().max(12 * 60 * 60),
  game_mode: nullableNonNegativeInteger,
  radiant_win: z.boolean(),
  radiant_score: nullableNonNegativeInteger,
  dire_score: nullableNonNegativeInteger,
  players: z.array(OpenDotaPlayerSchema).length(10),
  objectives: z.array(OpenDotaObjectiveSchema).max(512).nullable().optional(),
  teamfights: z.array(OpenDotaTeamfightSchema).max(256).nullable().optional(),
  radiant_gold_adv: z.array(z.number().int().safe().finite().nullable()).max(720).nullable().optional(),
  radiant_xp_adv: z.array(z.number().int().safe().finite().nullable()).max(720).nullable().optional(),
}).passthrough().superRefine((match, context) => {
  const matchId = String(match.match_id);
  if (!MATCH_ID_PATTERN.test(matchId)) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["match_id"], message: "invalid match ID" });
  }

  const slots = new Set(match.players.map((player) => player.player_slot));
  if (slots.size !== 10) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["players"], message: "player slots must be unique" });
  }
  if (match.players.filter((player) => player.player_slot < 128).length !== 5) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["players"], message: "match must contain five players per side" });
  }
  if (match.players.some((player, index) => player.player_slot !== CANONICAL_PLAYER_SLOTS[index])) {
    // Teamfight player entries and objective `slot` values are ordinal arrays.
    // Reject an ambiguous upstream ordering instead of silently mixing sides.
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["players"],
      message: "players must use canonical Dota slot order",
    });
  }
});

export type OpenDotaMatch = z.infer<typeof OpenDotaMatchSchema>;
export type AnalysisFetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export type FetchOpenDotaMatchOptions = {
  fetch?: AnalysisFetch;
  signal?: AbortSignal;
  timeoutMs?: number;
  maxResponseBytes?: number;
};

export function parseMatchId(input: string): string {
  if (typeof input !== "string" || !MATCH_ID_PATTERN.test(input)) {
    throw new AnalysisPublicError(
      "INVALID_MATCH_ID",
      "Match ID должен содержать от 8 до 12 цифр и не начинаться с нуля.",
      { httpStatus: 400, retryable: false },
    );
  }
  return input;
}

function retiredSource(matchIdInput: string): never {
  parseMatchId(matchIdInput);
  throw new AnalysisPublicError(
    "SOURCE_RETIRED",
    "Анализ по Match ID отключён. Загрузите игровой файл на новом сайте.",
    { httpStatus: 410, retryable: false },
  );
}

// Keep the historical call signatures so archived importers remain compatible.
// Options, including caller-injected fetch functions, cannot re-enable transport.
export async function fetchOpenDotaRoster(
  matchIdInput: string,
  ..._options: [FetchOpenDotaMatchOptions?]
): Promise<{ match_id: string | number; players: OpenDotaMatch["players"] }> {
  void _options;
  return retiredSource(matchIdInput);
}

export async function fetchOpenDotaMatch(
  matchIdInput: string,
  ..._options: [FetchOpenDotaMatchOptions?]
): Promise<OpenDotaMatch> {
  void _options;
  return retiredSource(matchIdInput);
}
