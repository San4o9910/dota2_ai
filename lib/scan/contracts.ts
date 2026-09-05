import { z } from "zod";

import {
  MATCH_ID_PATTERN,
  PlayerSlotSchema,
  TeamSideSchema,
} from "@/lib/analysis/contracts";

const nullableStat = z.number().int().nonnegative().safe().finite().nullable();

export const ScanRequestSchema = z.object({
  matchId: z.string().regex(MATCH_ID_PATTERN),
  playerSlot: PlayerSlotSchema.optional(),
}).strict();
export type ScanRequest = z.infer<typeof ScanRequestSchema>;

export const ScanRosterItemSchema = z.object({
  playerSlot: PlayerSlotSchema,
  heroId: z.number().int().positive().max(1024),
  side: TeamSideSchema,
  kills: nullableStat,
  deaths: nullableStat,
  assists: nullableStat,
}).strict();
export type ScanRosterItem = z.infer<typeof ScanRosterItemSchema>;

export type ScanChoosePlayerResponse = {
  status: "choose_player";
  match: {
    matchId: string;
    durationSeconds: number;
  };
  players: ScanRosterItem[];
};

export type ScanReadyResponse = {
  status: "ready";
  preview: import("@/lib/analysis/scan-preview").ScanPreviewV1;
};

export type ScanSuccessResponse = ScanChoosePlayerResponse | ScanReadyResponse;
