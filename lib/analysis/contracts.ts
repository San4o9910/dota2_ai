import { z } from "zod";
import { ReplayMapSchema } from "@/lib/replay/map-state";

export const MATCH_ID_PATTERN = /^[1-9]\d{7,11}$/;
export const SHA256_PATTERN = /^[a-f0-9]{64}$/;
export const NORMALIZED_MATCH_SCHEMA_VERSION = "normalized-match.v1" as const;
export const EVIDENCE_BUNDLE_SCHEMA_VERSION = "evidence-bundle.v1" as const;
export const ANALYSIS_REPORT_SCHEMA_VERSION = "analysis-report.v1" as const;

const nullableInt = z.number().int().safe().finite().nullable();
const nullableNonNegativeInt = z.number().int().nonnegative().safe().finite().nullable();

export const TeamSideSchema = z.enum(["radiant", "dire"]);
export type TeamSide = z.infer<typeof TeamSideSchema>;

export const PlayerSlotSchema = z.number().int().refine(
  (slot) => (slot >= 0 && slot <= 4) || (slot >= 128 && slot <= 132),
  "player slot must identify one of the ten Dota players",
);

export const NormalizedPlayerV1Schema = z.object({
  playerSlot: PlayerSlotSchema,
  heroId: z.number().int().positive().max(1024),
  isRadiant: z.boolean(),
  laneRole: z.number().int().min(0).max(5).nullable(),
  isRoaming: z.boolean().nullable(),
  kills: nullableNonNegativeInt,
  deaths: nullableNonNegativeInt,
  assists: nullableNonNegativeInt,
  lastHits: nullableNonNegativeInt,
  denies: nullableNonNegativeInt,
  goldPerMinute: nullableNonNegativeInt,
  xpPerMinute: nullableNonNegativeInt,
  level: z.number().int().min(0).max(100).nullable(),
  netWorth: nullableNonNegativeInt,
  observerWardsPlaced: nullableNonNegativeInt,
  sentryWardsPlaced: nullableNonNegativeInt,
  itemIds: z.array(z.number().int().nonnegative().max(1_000_000).nullable()).length(6),
}).strict();
export type NormalizedPlayerV1 = z.infer<typeof NormalizedPlayerV1Schema>;

export const TeamTotalsV1Schema = z.object({
  side: TeamSideSchema,
  playerCount: z.literal(5),
  kills: nullableNonNegativeInt,
  deaths: nullableNonNegativeInt,
  assists: nullableNonNegativeInt,
  lastHits: nullableNonNegativeInt,
  denies: nullableNonNegativeInt,
  netWorth: nullableNonNegativeInt,
  observerWardsPlaced: nullableNonNegativeInt,
  sentryWardsPlaced: nullableNonNegativeInt,
}).strict();

export const ObjectiveKindSchema = z.enum([
  "first_blood",
  "tower",
  "barracks",
  "roshan",
  "aegis",
  "aegis_stolen",
  "tormentor",
]);

export const NormalizedObjectiveV1Schema = z.object({
  id: z.string().regex(/^objective\.[a-z_]+\.\d{4}$/),
  kind: ObjectiveKindSchema,
  timeSeconds: z.number().int().min(-600).max(43200),
  team: TeamSideSchema.nullable(),
  playerSlot: PlayerSlotSchema.nullable(),
}).strict();

export const FightTeamV1Schema = z.object({
  kills: nullableNonNegativeInt,
  deaths: nullableNonNegativeInt,
  goldDelta: nullableInt,
  xpDelta: nullableInt,
  damage: nullableNonNegativeInt,
}).strict();

export const NormalizedFightV1Schema = z.object({
  id: z.string().regex(/^fight\.\d{4}$/),
  startSeconds: z.number().int().min(-600).max(43200),
  endSeconds: z.number().int().min(-600).max(43200),
  radiant: FightTeamV1Schema,
  dire: FightTeamV1Schema,
}).strict().refine((fight) => fight.endSeconds >= fight.startSeconds, {
  message: "fight end must not precede its start",
});

export const EconomySampleV1Schema = z.object({
  timeSeconds: z.number().int().min(-600).max(43200),
  radiantGoldAdvantage: nullableInt,
  radiantXpAdvantage: nullableInt,
}).strict().refine(
  (sample) => sample.radiantGoldAdvantage !== null || sample.radiantXpAdvantage !== null,
  { message: "economy sample must contain gold or XP" },
);

export const NormalizedMatchV1Schema = z.object({
  schemaVersion: z.literal(NORMALIZED_MATCH_SCHEMA_VERSION),
  source: z.literal("opendota"),
  matchId: z.string().regex(MATCH_ID_PATTERN),
  parserVersion: z.number().int().positive().safe().nullable(),
  patch: z.string().regex(/^\d+(?:\.\d+)*$/).max(32).nullable(),
  economyGoldBasis: z.enum(["total_earned","net_worth"]).optional(),
  startTime: nullableNonNegativeInt,
  durationSeconds: z.number().int().positive().max(12 * 60 * 60),
  gameMode: nullableNonNegativeInt,
  radiantWin: z.boolean(),
  winner: TeamSideSchema,
  radiantScore: nullableNonNegativeInt,
  direScore: nullableNonNegativeInt,
  players: z.array(NormalizedPlayerV1Schema).length(10),
  teamTotals: z.object({
    radiant: TeamTotalsV1Schema,
    dire: TeamTotalsV1Schema,
  }).strict(),
  objectives: z.array(NormalizedObjectiveV1Schema).max(256),
  fights: z.array(NormalizedFightV1Schema).max(128),
  economy: z.array(EconomySampleV1Schema).max(180),
  replayMap: ReplayMapSchema.optional(),
}).strict().superRefine((match, context) => {
  const slots = new Set(match.players.map((player) => player.playerSlot));
  if (slots.size !== match.players.length) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["players"], message: "player slots must be unique" });
  }

  for (const [index, player] of match.players.entries()) {
    if (player.isRadiant !== (player.playerSlot < 128)) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["players", index, "isRadiant"],
        message: "player side does not match player slot",
      });
    }
  }

  const radiantCount = match.players.filter((player) => player.isRadiant).length;
  if (radiantCount !== 5) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["players"], message: "match must have five players per side" });
  }
  if (match.teamTotals.radiant.side !== "radiant" || match.teamTotals.dire.side !== "dire") {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["teamTotals"], message: "team total sides are invalid" });
  }

  match.objectives.forEach((objective, index) => {
    if (objective.timeSeconds > match.durationSeconds) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["objectives", index, "timeSeconds"], message: "objective is outside match duration" });
    }
  });
  match.fights.forEach((fight, index) => {
    if (fight.endSeconds > match.durationSeconds) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["fights", index, "endSeconds"], message: "fight is outside match duration" });
    }
  });
  match.economy.forEach((sample, index) => {
    if (sample.timeSeconds > match.durationSeconds) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["economy", index, "timeSeconds"], message: "economy sample is outside match duration" });
    }
  });
});
export type NormalizedMatchV1 = z.infer<typeof NormalizedMatchV1Schema>;

export const EVIDENCE_UNITS = [
  "count",
  "gold",
  "xp",
  "gpm",
  "xpm",
  "seconds",
  "score",
  "hero_id",
  "item_id",
  "level",
  "lane_role",
  "flag",
  "damage",
] as const;
export const EvidenceUnitSchema = z.enum(EVIDENCE_UNITS);
export type EvidenceUnit = z.infer<typeof EvidenceUnitSchema>;

export const EvidenceValueV1Schema = z.object({
  metric: z.string().regex(/^[a-z][a-z0-9_]{1,63}$/),
  value: z.number().finite(),
  unit: EvidenceUnitSchema,
}).strict();

export const EvidencePointTimeV1Schema = z.object({
  type: z.literal("point"),
  seconds: z.number().int().min(-600).max(43200),
}).strict();

export const EvidenceWindowTimeV1Schema = z.object({
  type: z.literal("window"),
  startSeconds: z.number().int().min(-600).max(43200),
  endSeconds: z.number().int().min(-600).max(43200),
}).strict().refine((time) => time.endSeconds >= time.startSeconds, {
  message: "evidence window end must not precede its start",
});

export const EvidenceTimeV1Schema = z.union([
  z.null(),
  EvidencePointTimeV1Schema,
  EvidenceWindowTimeV1Schema,
]);
export type EvidenceTimeV1 = z.infer<typeof EvidenceTimeV1Schema>;

export const EvidenceItemV1Schema = z.object({
  id: z.string().regex(/^[a-z][a-z0-9_.:-]{2,127}$/),
  kind: z.enum(["match", "team", "player", "objective", "fight", "economy"]),
  time: EvidenceTimeV1Schema,
  team: TeamSideSchema.nullable(),
  playerSlot: PlayerSlotSchema.nullable(),
  values: z.array(EvidenceValueV1Schema).min(1).max(32),
  summary: z.string().trim().min(1).max(280),
}).strict();
export type EvidenceItemV1 = z.infer<typeof EvidenceItemV1Schema>;

export const EvidenceBundleV1Schema = z.object({
  schemaVersion: z.literal(EVIDENCE_BUNDLE_SCHEMA_VERSION),
  matchId: z.string().regex(MATCH_ID_PATTERN),
  normalizedMatchHash: z.string().regex(SHA256_PATTERN),
  patch: z.string().max(32).nullable().optional(),
  capabilities: z.object({
    economy: z.boolean(), objectiveEvents: z.boolean(), wardLifetimes: z.boolean(),
    heroPositions: z.literal(false), teamVision: z.literal(false), abilityState: z.literal(false), playerInputs: z.literal(false),
  }).strict().optional(),
  durationSeconds: z.number().int().positive().max(12 * 60 * 60),
  evidence: z.array(EvidenceItemV1Schema).min(1).max(1024),
}).strict().superRefine((bundle, context) => {
  const ids = new Set<string>();
  bundle.evidence.forEach((item, index) => {
    if (ids.has(item.id)) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["evidence", index, "id"], message: "evidence IDs must be unique" });
    }
    ids.add(item.id);
    if (item.time?.type === "point" && item.time.seconds > bundle.durationSeconds) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["evidence", index, "time"], message: "evidence time is outside match duration" });
    }
    if (item.time?.type === "window" && item.time.endSeconds > bundle.durationSeconds) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["evidence", index, "time"], message: "evidence window is outside match duration" });
    }
  });
});
export type EvidenceBundleV1 = z.infer<typeof EvidenceBundleV1Schema>;

export const AnalysisStageSchema = z.enum(["draft", "laning", "mid", "late", "overall"]);

const NUMERIC_PROSE_CHARACTER = /\p{N}/u;
const QUANTITATIVE_PROSE_SYMBOL = /[%‰‱∞±≈≠≤≥<>=]/u;
const PROSE_WORD = /[\p{L}\p{M}]+/gu;
const QUANTITATIVE_PROSE_WORDS = new Set([
  "один", "одна", "одно", "одну", "одни", "одного", "одной", "одному", "одним", "одних", "однажды",
  "два", "две", "двух", "двум", "двумя", "двое", "двоих", "двоим", "двоими", "вдвое",
  "три", "трёх", "трех", "трём", "трем", "тремя", "трое", "троих", "троим", "троими", "трижды", "втрое",
  "ноль", "нуль", "нуля", "нулю", "нулём", "нулем", "семь", "семи", "семью", "семеро",
  "сорок", "сорока", "сто", "ста", "около", "примерно", "приблизительно",
  "пара", "пары", "пару", "раз", "раза", "разы", "несколько", "много", "мало",
  "доля", "доли", "долю", "долей",
  "более", "менее", "больше", "меньше", "выше", "ниже", "минимум", "максимум",
  "плюс", "минус", "нан", "бесконечность", "положительный", "положительная", "отрицательный", "отрицательная",
  "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
  "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
  "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
  "hundred", "thousand", "million", "billion", "first", "second", "third", "fourth", "fifth",
  "sixth", "seventh", "eighth", "ninth", "tenth", "half", "quarter", "double", "triple", "once", "twice", "thrice", "times", "percent", "percentage", "ratio",
  "more", "less", "fewer", "higher", "lower", "minimum", "maximum", "several", "many", "few",
  "about", "approximately", "plus", "minus", "positive", "negative", "nan", "infinity", "dozen",
]);
const QUANTITATIVE_PROSE_PREFIXES = [
  "нулев", "перв", "втор", "трет", "треть", "четыр", "четвер", "пят", "шест", "седьм", "восем", "восьм", "девят", "десят",
  "одиннадцат", "двенадцат", "тринадцат", "четырнадцат", "пятнадцат", "шестнадцат", "семнадцат", "восемнадцат", "девятнадцат",
  "двадцат", "тридцат", "пятьдесят", "пятидесят", "шестьдесят", "шестидесят", "семьдесят", "семидесят", "восемьдесят", "восьмидесят", "девяност",
  "сотн", "двухсот", "трехсот", "трёхсот", "четырехсот", "четырёхсот", "пятисот", "шестисот", "семисот", "восьмисот", "девятисот",
  "тысяч", "миллион", "миллиард", "триллион", "двойн", "тройн", "двукрат", "трехкрат", "трёхкрат", "многократ", "кратн",
  "половин", "процент", "соотношен", "дюжин",
] as const;

function containsUnstructuredQuantity(value: string): boolean {
  if (NUMERIC_PROSE_CHARACTER.test(value) || QUANTITATIVE_PROSE_SYMBOL.test(value)) return true;
  // Natural-language paraphrases are unbounded. This conservative RU/EN guard
  // supplements the hard numeric-character ban; only claims are factual data.
  const words = value.normalize("NFKC").toLowerCase().match(PROSE_WORD) ?? [];
  return words.some((word) =>
    QUANTITATIVE_PROSE_WORDS.has(word)
    || QUANTITATIVE_PROSE_PREFIXES.some((prefix) => word.startsWith(prefix)));
}

function reportProse(maxLength: number) {
  return z.string().trim().min(1).max(maxLength).refine(
    (value) => !containsUnstructuredQuantity(value),
    "report prose must not contain unstructured quantitative language; use structured claims",
  );
}

export const AnalysisNumericClaimV1Schema = z.object({
  evidenceId: z.string().regex(/^[a-z][a-z0-9_.:-]{2,127}$/),
  metric: z.string().regex(/^[a-z][a-z0-9_]{1,63}$/),
  value: z.number().finite(),
  unit: EvidenceUnitSchema,
}).strict();
export type AnalysisNumericClaimV1 = z.infer<typeof AnalysisNumericClaimV1Schema>;

export const AnalysisReportItemV1Schema = z.object({
  id: z.string().regex(/^item\.[a-z0-9_-]{1,80}$/),
  kind: z.enum(["inference", "advice"]),
  stage: AnalysisStageSchema,
  title: reportProse(120),
  body: reportProse(1000),
  evidenceIds: z.array(z.string().min(3).max(128)).min(1).max(12),
  claims: z.array(AnalysisNumericClaimV1Schema).min(1).max(12),
  confidence: z.enum(["low", "medium", "high"]),
  limitations: z.array(reportProse(240)).max(5),
  time: EvidenceTimeV1Schema,
  playerSlot: PlayerSlotSchema.nullable(),
}).strict().superRefine((item, context) => {
  if (new Set(item.evidenceIds).size !== item.evidenceIds.length) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["evidenceIds"], message: "evidence IDs must be unique within an item" });
  }
  const claimKeys = new Set<string>();
  item.claims.forEach((claim, index) => {
    const key = `${claim.evidenceId}\0${claim.metric}\0${claim.unit}`;
    if (claimKeys.has(key)) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["claims", index],
        message: "numeric claims must be unique within an item",
      });
    }
    claimKeys.add(key);
  });
});

export const AnalysisReportV1Schema = z.object({
  schemaVersion: z.literal(ANALYSIS_REPORT_SCHEMA_VERSION),
  matchId: z.string().regex(MATCH_ID_PATTERN),
  playerSlot: PlayerSlotSchema.nullable(),
  evidenceHash: z.string().regex(SHA256_PATTERN),
  items: z.array(AnalysisReportItemV1Schema).min(1).max(20),
  limitations: z.array(reportProse(240)).max(10),
}).strict().superRefine((report, context) => {
  const ids = new Set<string>();
  report.items.forEach((item, index) => {
    if (ids.has(item.id)) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["items", index, "id"], message: "report item IDs must be unique" });
    }
    ids.add(item.id);
  });
});
export type AnalysisReportV1 = z.infer<typeof AnalysisReportV1Schema>;

const playerSlotJsonSchema = {
  anyOf: [
    { type: "integer", enum: [0, 1, 2, 3, 4, 128, 129, 130, 131, 132] },
    { type: "null" },
  ],
} as const;

const timeJsonSchema = {
  anyOf: [
    { type: "null" },
    {
      type: "object",
      properties: {
        type: { type: "string", enum: ["point"] },
        seconds: { type: "integer", minimum: -600, maximum: 43200 },
      },
      required: ["type", "seconds"],
      additionalProperties: false,
    },
    {
      type: "object",
      properties: {
        type: { type: "string", enum: ["window"] },
        startSeconds: { type: "integer", minimum: -600, maximum: 43200 },
        endSeconds: { type: "integer", minimum: -600, maximum: 43200 },
      },
      required: ["type", "startSeconds", "endSeconds"],
      additionalProperties: false,
    },
  ],
} as const;

const numericClaimJsonSchema = {
  type: "object",
  properties: {
    evidenceId: { type: "string", pattern: "^[a-z][a-z0-9_.:-]{2,127}$" },
    metric: { type: "string", pattern: "^[a-z][a-z0-9_]{1,63}$" },
    value: { type: "number" },
    unit: { type: "string", enum: EVIDENCE_UNITS },
  },
  required: ["evidenceId", "metric", "value", "unit"],
  additionalProperties: false,
} as const;

function reportProseJsonSchema(maxLength: number) {
  return {
    type: "string",
    minLength: 1,
    maxLength,
    // The server applies a stricter Unicode-number check after generation.
    pattern: "^[^0-9]*$",
  } as const;
}

/** JSON Schema sent to Responses API through text.format with strict=true. */
export const ANALYSIS_REPORT_V1_JSON_SCHEMA = {
  type: "object",
  properties: {
    schemaVersion: { type: "string", enum: [ANALYSIS_REPORT_SCHEMA_VERSION] },
    matchId: { type: "string", pattern: MATCH_ID_PATTERN.source },
    playerSlot: playerSlotJsonSchema,
    evidenceHash: { type: "string", pattern: SHA256_PATTERN.source },
    items: {
      type: "array",
      minItems: 1,
      maxItems: 20,
      items: {
        type: "object",
        properties: {
          id: { type: "string", pattern: "^item\\.[a-z0-9_-]{1,80}$" },
          kind: { type: "string", enum: ["inference", "advice"] },
          stage: { type: "string", enum: ["draft", "laning", "mid", "late", "overall"] },
          title: reportProseJsonSchema(120),
          body: reportProseJsonSchema(1000),
          evidenceIds: {
            type: "array",
            minItems: 1,
            maxItems: 12,
            items: { type: "string", minLength: 3, maxLength: 128 },
          },
          claims: {
            type: "array",
            minItems: 1,
            maxItems: 12,
            items: numericClaimJsonSchema,
          },
          confidence: { type: "string", enum: ["low", "medium", "high"] },
          limitations: {
            type: "array",
            maxItems: 5,
            items: reportProseJsonSchema(240),
          },
          time: timeJsonSchema,
          playerSlot: playerSlotJsonSchema,
        },
        required: ["id", "kind", "stage", "title", "body", "evidenceIds", "claims", "confidence", "limitations", "time", "playerSlot"],
        additionalProperties: false,
      },
    },
    limitations: {
      type: "array",
      maxItems: 10,
      items: reportProseJsonSchema(240),
    },
  },
  required: ["schemaVersion", "matchId", "playerSlot", "evidenceHash", "items", "limitations"],
  additionalProperties: false,
} as const;
