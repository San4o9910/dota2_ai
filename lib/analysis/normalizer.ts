import {
  EVIDENCE_BUNDLE_SCHEMA_VERSION,
  EvidenceBundleV1Schema,
  type EvidenceBundleV1,
  type EvidenceItemV1,
  NORMALIZED_MATCH_SCHEMA_VERSION,
  NormalizedMatchV1Schema,
  PlayerSlotSchema,
  type NormalizedMatchV1,
  type NormalizedPlayerV1,
  type TeamSide,
} from "@/lib/analysis/contracts";
import { canonicalJson, canonicalSha256 } from "@/lib/analysis/canonical-json";
import type { OpenDotaMatch } from "@/lib/analysis/opendota";
import { normalizeReplayMap } from "@/lib/replay/normalize-map";

function nullable<T>(value: T | null | undefined): T | null {
  return value ?? null;
}

import patchCatalog from "@/app/data/patch-catalog.json";

function normalizePatch(value: string | number | null | undefined): string | null {
  if (typeof value === "number" && Number.isFinite(value) && value >= 0) return (patchCatalog as Record<string,string>)[String(value)] ?? String(value);
  if (typeof value === "string" && /^\d+(?:\.\d+)*$/.test(value) && value.length <= 32) return value;
  return null;
}

function compareAscii(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function sumWhenComplete(
  players: NormalizedPlayerV1[],
  field: Exclude<keyof NormalizedPlayerV1, "playerSlot" | "heroId" | "isRadiant" | "laneRole" | "isRoaming" | "level" | "itemIds">,
): number | null {
  const values = players.map((player) => player[field]);
  return values.every((value): value is number => typeof value === "number")
    ? values.reduce((sum, value) => sum + value, 0)
    : null;
}

function teamFromNumber(value: number | null | undefined): TeamSide | null {
  if (value === 2) return "radiant";
  if (value === 3) return "dire";
  return null;
}

function objectiveKind(type: string, key: string | number | null | undefined) {
  switch (type) {
    case "CHAT_MESSAGE_FIRSTBLOOD": return "first_blood" as const;
    case "CHAT_MESSAGE_ROSHAN_KILL": return "roshan" as const;
    case "CHAT_MESSAGE_AEGIS": return "aegis" as const;
    case "CHAT_MESSAGE_AEGIS_STOLEN": return "aegis_stolen" as const;
    case "CHAT_MESSAGE_MINIBOSS_KILL":
    case "CHAT_MESSAGE_TORMENTOR_KILL": return "tormentor" as const;
    case "building_kill": {
      const building = typeof key === "string" ? key.toLowerCase() : "";
      if (building.includes("tower")) return "tower" as const;
      if (building.includes("rax") || building.includes("barracks")) return "barracks" as const;
      return null;
    }
    default: return null;
  }
}

function normalizeObjectiveSlot(
  rawPlayerSlot: number | null | undefined,
  rawSlot: number | null | undefined,
  players: OpenDotaMatch["players"],
): number | null {
  const direct = PlayerSlotSchema.safeParse(rawPlayerSlot);
  if (direct.success) return direct.data;
  if (rawSlot != null && Number.isInteger(rawSlot) && rawSlot >= 0 && rawSlot < players.length) {
    return players[rawSlot].player_slot;
  }
  return null;
}

function sumRaw(
  players: Array<Record<string, unknown>>,
  field: "deaths" | "gold_delta" | "xp_delta" | "damage",
): number | null {
  const values = players.map((player) => player[field]);
  if (!values.every((value): value is number => typeof value === "number" && Number.isFinite(value))) return null;
  return values.reduce((sum, value) => sum + value, 0);
}

export function normalizeOpenDotaMatch(raw: OpenDotaMatch): NormalizedMatchV1 {
  const players: NormalizedPlayerV1[] = raw.players
    .map((player) => ({
      playerSlot: player.player_slot,
      heroId: player.hero_id,
      isRadiant: player.player_slot < 128,
      laneRole: nullable(player.lane_role),
      isRoaming: nullable(player.is_roaming),
      kills: nullable(player.kills),
      deaths: nullable(player.deaths),
      assists: nullable(player.assists),
      lastHits: nullable(player.last_hits),
      denies: nullable(player.denies),
      goldPerMinute: nullable(player.gold_per_min),
      xpPerMinute: nullable(player.xp_per_min),
      level: nullable(player.level),
      netWorth: nullable(player.net_worth),
      observerWardsPlaced: nullable(player.obs_placed),
      sentryWardsPlaced: nullable(player.sen_placed),
      itemIds: [player.item_0, player.item_1, player.item_2, player.item_3, player.item_4, player.item_5].map(nullable),
    }))
    .sort((left, right) => left.playerSlot - right.playerSlot);

  const normalizedObjectives = (raw.objectives ?? [])
    .flatMap((objective) => {
      const kind = objectiveKind(objective.type, objective.key);
      if (!kind || objective.time > raw.duration) return [];
      return [{
        kind,
        timeSeconds: objective.time,
        team: teamFromNumber(objective.team),
        playerSlot: normalizeObjectiveSlot(objective.player_slot, objective.slot, raw.players),
      }];
    })
    .sort((left, right) =>
      left.timeSeconds - right.timeSeconds
      || compareAscii(left.kind, right.kind)
      || compareAscii(left.team ?? "", right.team ?? "")
      || (left.playerSlot ?? -1) - (right.playerSlot ?? -1))
    .slice(0, 256)
    .map((objective, index) => ({
      id: `objective.${objective.kind}.${String(index).padStart(4, "0")}`,
      ...objective,
    }));

  const normalizedFights = (raw.teamfights ?? [])
    .filter((fight) => fight.end <= raw.duration)
    .map((fight) => {
      const radiantPlayers = fight.players.filter((_, index) => raw.players[index].player_slot < 128);
      const direPlayers = fight.players.filter((_, index) => raw.players[index].player_slot >= 128);
      const radiantDeaths = sumRaw(radiantPlayers, "deaths");
      const direDeaths = sumRaw(direPlayers, "deaths");
      return {
        players: fight.players.map((player,index)=>({playerSlot:raw.players[index].player_slot,heroId:nullable(raw.players[index].hero_id),goldDelta:nullable(player.gold_delta),xpDelta:nullable(player.xp_delta)})),
        startSeconds: fight.start,
        endSeconds: fight.end,
        radiant: {
          kills: direDeaths,
          deaths: radiantDeaths,
          goldDelta: sumRaw(radiantPlayers, "gold_delta"),
          xpDelta: sumRaw(radiantPlayers, "xp_delta"),
          damage: sumRaw(radiantPlayers, "damage"),
        },
        dire: {
          kills: radiantDeaths,
          deaths: direDeaths,
          goldDelta: sumRaw(direPlayers, "gold_delta"),
          xpDelta: sumRaw(direPlayers, "xp_delta"),
          damage: sumRaw(direPlayers, "damage"),
        },
      };
    })
    .sort((left, right) =>
      left.startSeconds - right.startSeconds
      || left.endSeconds - right.endSeconds
      || compareAscii(canonicalJson(left), canonicalJson(right)))
    .slice(0, 128)
    .map((fight, index) => ({ id: `fight.${String(index).padStart(4, "0")}`, ...fight }));

  const economyLength = Math.max(raw.radiant_gold_adv?.length ?? 0, raw.radiant_xp_adv?.length ?? 0);
  const economy = Array.from({ length: economyLength }, (_, index) => ({
    timeSeconds: index * 60,
    radiantGoldAdvantage: nullable(raw.radiant_gold_adv?.[index]),
    radiantXpAdvantage: nullable(raw.radiant_xp_adv?.[index]),
  }))
    .filter((sample) => sample.timeSeconds <= raw.duration
      && (sample.radiantGoldAdvantage !== null || sample.radiantXpAdvantage !== null))
    .slice(0, 180);

  const radiantPlayers = players.filter((player) => player.isRadiant);
  const direPlayers = players.filter((player) => !player.isRadiant);
  const teamTotals = (side: TeamSide, teamPlayers: NormalizedPlayerV1[]) => ({
    side,
    playerCount: 5 as const,
    kills: sumWhenComplete(teamPlayers, "kills"),
    deaths: sumWhenComplete(teamPlayers, "deaths"),
    assists: sumWhenComplete(teamPlayers, "assists"),
    lastHits: sumWhenComplete(teamPlayers, "lastHits"),
    denies: sumWhenComplete(teamPlayers, "denies"),
    netWorth: sumWhenComplete(teamPlayers, "netWorth"),
    observerWardsPlaced: sumWhenComplete(teamPlayers, "observerWardsPlaced"),
    sentryWardsPlaced: sumWhenComplete(teamPlayers, "sentryWardsPlaced"),
  });

  return NormalizedMatchV1Schema.parse({
    schemaVersion: NORMALIZED_MATCH_SCHEMA_VERSION,
    source: "opendota",
    matchId: String(raw.match_id),
    parserVersion: raw.version ?? null,
    patch: normalizePatch(raw.patch),
    economyGoldBasis: raw._narma_gold_basis === "net_worth" ? "net_worth" : "total_earned",
    startTime: nullable(raw.start_time),
    durationSeconds: raw.duration,
    gameMode: nullable(raw.game_mode),
    radiantWin: raw.radiant_win,
    winner: raw.radiant_win ? "radiant" : "dire",
    radiantScore: nullable(raw.radiant_score),
    direScore: nullable(raw.dire_score),
    players,
    teamTotals: {
      radiant: teamTotals("radiant", radiantPlayers),
      dire: teamTotals("dire", direPlayers),
    },
    objectives: normalizedObjectives,
    fights: normalizedFights,
    economy,
    replayMap: normalizeReplayMap(raw),
  });
}

function pushValue(
  values: EvidenceItemV1["values"],
  metric: string,
  value: number | null,
  unit: EvidenceItemV1["values"][number]["unit"],
) {
  if (value !== null) values.push({ metric, value, unit });
}

function teamEvidence(match: NormalizedMatchV1, side: TeamSide): EvidenceItemV1 {
  const totals = match.teamTotals[side];
  const values: EvidenceItemV1["values"] = [{ metric: "player_count", value: 5, unit: "count" }];
  pushValue(values, "kills", totals.kills, "count");
  pushValue(values, "deaths", totals.deaths, "count");
  pushValue(values, "assists", totals.assists, "count");
  pushValue(values, "last_hits", totals.lastHits, "count");
  pushValue(values, "denies", totals.denies, "count");
  pushValue(values, "net_worth", totals.netWorth, "gold");
  pushValue(values, "observer_wards", totals.observerWardsPlaced, "count");
  pushValue(values, "sentry_wards", totals.sentryWardsPlaced, "count");
  return {
    id: `team.${side}.totals`,
    kind: "team",
    time: null,
    team: side,
    playerSlot: null,
    values,
    summary: `${side} team totals from five player records.`,
  };
}

function playerEvidence(player: NormalizedPlayerV1): EvidenceItemV1 {
  const values: EvidenceItemV1["values"] = [{ metric: "hero_id", value: player.heroId, unit: "hero_id" }];
  pushValue(values, "kills", player.kills, "count");
  pushValue(values, "deaths", player.deaths, "count");
  pushValue(values, "assists", player.assists, "count");
  pushValue(values, "last_hits", player.lastHits, "count");
  pushValue(values, "denies", player.denies, "count");
  pushValue(values, "gold_per_minute", player.goldPerMinute, "gpm");
  pushValue(values, "xp_per_minute", player.xpPerMinute, "xpm");
  pushValue(values, "level", player.level, "level");
  pushValue(values, "lane_role", player.laneRole, "lane_role");
  pushValue(values, "is_roaming", player.isRoaming === null ? null : Number(player.isRoaming), "flag");
  pushValue(values, "net_worth", player.netWorth, "gold");
  pushValue(values, "observer_wards", player.observerWardsPlaced, "count");
  pushValue(values, "sentry_wards", player.sentryWardsPlaced, "count");
  player.itemIds.forEach((itemId, index) => {
    if (itemId !== null && itemId !== 0) pushValue(values, `item_${index}`, itemId, "item_id");
  });
  return {
    id: `player.${String(player.playerSlot).padStart(3, "0")}.summary`,
    kind: "player",
    time: null,
    team: player.isRadiant ? "radiant" : "dire",
    playerSlot: player.playerSlot,
    values,
    summary: `Player slot ${player.playerSlot} used hero ${player.heroId}; nullable metrics are omitted.`,
  };
}

export type EvidenceArtifactsV1 = {
  normalizedMatchHash: string;
  evidenceBundle: EvidenceBundleV1;
  evidenceHash: string;
};

export async function buildEvidenceBundle(matchInput: NormalizedMatchV1): Promise<EvidenceArtifactsV1> {
  const match = NormalizedMatchV1Schema.parse(matchInput);
  const normalizedMatchHash = await canonicalSha256(match);
  const evidence: EvidenceItemV1[] = [];

  const matchValues: EvidenceItemV1["values"] = [
    { metric: "duration", value: match.durationSeconds, unit: "seconds" },
  ];
  pushValue(matchValues, "radiant_score", match.radiantScore, "score");
  pushValue(matchValues, "dire_score", match.direScore, "score");
  evidence.push({
    id: "match.summary",
    kind: "match",
    time: { type: "window", startSeconds: 0, endSeconds: match.durationSeconds },
    team: match.winner,
    playerSlot: null,
    values: matchValues,
    summary: `${match.winner} won a ${match.durationSeconds}-second match.`,
  });
  evidence.push(teamEvidence(match, "radiant"), teamEvidence(match, "dire"));
  evidence.push(...match.players.map(playerEvidence));

  for (const objective of match.objectives) {
    evidence.push({
      id: objective.id,
      kind: "objective",
      time: { type: "point", seconds: objective.timeSeconds },
      team: objective.team,
      playerSlot: objective.playerSlot,
      values: [{ metric: "occurrences", value: 1, unit: "count" }],
      summary: `${objective.kind} event at ${objective.timeSeconds} seconds.`,
    });
  }
  for (const fight of match.fights) {
    const values: EvidenceItemV1["values"] = [
      { metric: "duration", value: fight.endSeconds - fight.startSeconds, unit: "seconds" },
    ];
    pushValue(values, "radiant_kills", fight.radiant.kills, "count");
    pushValue(values, "radiant_deaths", fight.radiant.deaths, "count");
    pushValue(values, "radiant_gold_delta", fight.radiant.goldDelta, "gold");
    pushValue(values, "radiant_xp_delta", fight.radiant.xpDelta, "xp");
    pushValue(values, "radiant_damage", fight.radiant.damage, "damage");
    pushValue(values, "dire_kills", fight.dire.kills, "count");
    pushValue(values, "dire_deaths", fight.dire.deaths, "count");
    pushValue(values, "dire_gold_delta", fight.dire.goldDelta, "gold");
    pushValue(values, "dire_xp_delta", fight.dire.xpDelta, "xp");
    pushValue(values, "dire_damage", fight.dire.damage, "damage");
    evidence.push({
      id: fight.id,
      kind: "fight",
      time: { type: "window", startSeconds: fight.startSeconds, endSeconds: fight.endSeconds },
      team: null,
      playerSlot: null,
      values,
      summary: `Teamfight window from ${fight.startSeconds} to ${fight.endSeconds} seconds.`,
    });
  }
  match.economy.forEach((sample, index) => {
    const values: EvidenceItemV1["values"] = [];
    pushValue(values, "radiant_gold_advantage", sample.radiantGoldAdvantage, "gold");
    pushValue(values, "radiant_xp_advantage", sample.radiantXpAdvantage, "xp");
    evidence.push({
      id: `economy.${String(index).padStart(4, "0")}`,
      kind: "economy",
      time: { type: "point", seconds: sample.timeSeconds },
      team: null,
      playerSlot: null,
      values,
      summary: `Radiant economy advantage sample at ${sample.timeSeconds} seconds.`,
    });
  });

  const evidenceBundle = EvidenceBundleV1Schema.parse({
    schemaVersion: EVIDENCE_BUNDLE_SCHEMA_VERSION,
    matchId: match.matchId,
    normalizedMatchHash,
    patch: match.patch,
    capabilities: {economy:match.economy.length>0,objectiveEvents:match.objectives.length>0,wardLifetimes:match.replayMap?.wardLifetimesComplete ?? false,heroPositions:false,teamVision:false,abilityState:false,playerInputs:false},
    durationSeconds: match.durationSeconds,
    evidence,
  });
  return {
    normalizedMatchHash,
    evidenceBundle,
    evidenceHash: await canonicalSha256(evidenceBundle),
  };
}
