import { z } from "zod";

import { MATCH_ID_PATTERN, PlayerSlotSchema } from "@/lib/analysis/contracts";
import {
  AnalysisDependencyError,
  AnalysisPublicError,
  analysisCancelled,
  parseRetryAfterSeconds,
} from "@/lib/analysis/errors";
import { cancelResponseBody, createTimeoutContext, readBoundedJson } from "@/lib/analysis/http";

export const OPENDOTA_ORIGIN = "https://api.opendota.com" as const;
const DEFAULT_TIMEOUT_MS = 8_000;
const DEFAULT_MAX_RESPONSE_BYTES = 8 * 1024 * 1024;
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

function openDotaFailure(
  code: "OPENDOTA_RATE_LIMITED" | "OPENDOTA_UNAVAILABLE" | "OPENDOTA_INVALID_RESPONSE",
  message: string,
  retryable: boolean,
  options: { cause?: unknown; retryAfterSeconds?: number } = {},
) {
  return new AnalysisDependencyError("opendota", code, message, {
    cause: options.cause,
    httpStatus: 503,
    retryable,
    retryAfterSeconds: options.retryAfterSeconds,
  });
}

export async function fetchOpenDotaMatch(
  matchIdInput: string,
  options: FetchOpenDotaMatchOptions = {},
): Promise<OpenDotaMatch> {
  const matchId = parseMatchId(matchIdInput);
  const fetchImplementation = options.fetch ?? globalThis.fetch;
  if (typeof fetchImplementation !== "function") {
    throw openDotaFailure("OPENDOTA_UNAVAILABLE", "OpenDota временно недоступен.", true);
  }

  // The caller controls only a digits-only path segment. The origin, protocol,
  // method and redirect behavior are deliberately not configurable.
  const url = new URL(`/api/matches/${matchId}`, OPENDOTA_ORIGIN);
  const timeout = createTimeoutContext(options.timeoutMs ?? DEFAULT_TIMEOUT_MS, options.signal);
  try {
    if (options.signal?.aborted) throw analysisCancelled(options.signal.reason);
    let response: Response;
    try {
      response = await fetchImplementation(url, {
        method: "GET",
        headers: { accept: "application/json" },
        redirect: "error",
        signal: timeout.signal,
      });
    } catch (error) {
      if (options.signal?.aborted && !timeout.timedOut()) throw analysisCancelled(error);
      throw openDotaFailure(
        "OPENDOTA_UNAVAILABLE",
        timeout.timedOut() ? "OpenDota не ответил вовремя." : "Не удалось связаться с OpenDota.",
        true,
        { cause: error },
      );
    }

    if (response.status === 404) {
      await cancelResponseBody(response);
      throw new AnalysisPublicError(
        "OPENDOTA_MATCH_NOT_FOUND",
        "Матч с таким Match ID не найден в OpenDota.",
        { httpStatus: 404, retryable: false },
      );
    }
    if (response.status === 429) {
      await cancelResponseBody(response);
      throw openDotaFailure("OPENDOTA_RATE_LIMITED", "OpenDota временно ограничил частоту запросов.", true, {
        retryAfterSeconds: parseRetryAfterSeconds(response.headers.get("retry-after")),
      });
    }
    if (response.status >= 500 && response.status <= 599) {
      await cancelResponseBody(response);
      throw openDotaFailure("OPENDOTA_UNAVAILABLE", "OpenDota временно недоступен.", true);
    }
    if (!response.ok) {
      await cancelResponseBody(response);
      throw openDotaFailure("OPENDOTA_INVALID_RESPONSE", "OpenDota отклонил безопасный запрос матча.", false);
    }

    let raw: unknown;
    try {
      raw = await readBoundedJson(response, {
        dependency: "opendota",
        maxBytes: options.maxResponseBytes ?? DEFAULT_MAX_RESPONSE_BYTES,
        signal: timeout.signal,
      });
    } catch (error) {
      if (timeout.timedOut()) {
        throw openDotaFailure("OPENDOTA_UNAVAILABLE", "OpenDota не ответил вовремя.", true, { cause: error });
      }
      if (options.signal?.aborted) throw analysisCancelled(error);
      throw error;
    }
    const parsed = OpenDotaMatchSchema.safeParse(raw);
    if (!parsed.success) {
      throw openDotaFailure(
        "OPENDOTA_INVALID_RESPONSE",
        "OpenDota вернул неполные или некорректные данные матча.",
        false,
        { cause: parsed.error },
      );
    }
    if (String(parsed.data.match_id) !== matchId) {
      throw openDotaFailure("OPENDOTA_INVALID_RESPONSE", "OpenDota вернул данные другого матча.", false);
    }
    if (parsed.data.version == null) {
      throw new AnalysisDependencyError(
        "opendota",
        "OPENDOTA_MATCH_NOT_PARSED",
        "Матч найден, но расширенная статистика OpenDota ещё не готова.",
        { httpStatus: 503, retryable: false },
      );
    }
    return parsed.data;
  } finally {
    timeout.cleanup();
  }
}
