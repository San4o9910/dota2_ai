export type ScanSide = "radiant" | "dire";

export type ScanPlayer = {
  playerSlot: number;
  heroId: number;
  side: ScanSide;
  kills: number | null;
  deaths: number | null;
  assists: number | null;
};

export type ScanMetric = {
  metric: string;
  value: number;
  unit: string;
};

export type ScanPreview = {
  schemaVersion: string;
  matchId: string;
  playerSlot: number;
  selectedEvidenceId: string;
  kind: "match" | "objective" | "fight" | "economy";
  atSeconds: number;
  team: ScanSide | null;
  metrics: ScanMetric[];
};

export type ScanChoosePlayerResponse = {
  status: "choose_player";
  match: {
    matchId: string;
    durationSeconds: number;
  };
  players: ScanPlayer[];
};

export type ScanReadyResponse = {
  status: "ready";
  preview: ScanPreview;
};

export type ScanSuccessResponse = ScanChoosePlayerResponse | ScanReadyResponse;

export type ScanErrorResponse = {
  error: {
    code: string;
    message: string;
    retryable: boolean;
    requestId: string;
  };
};

const MATCH_ID = /^[1-9]\d{7,11}$/;
const ERROR_CODE = /^[A-Z][A-Z0-9_]{1,63}$/;
const REQUEST_ID = /^[a-zA-Z0-9_-]{1,128}$/;
const EVIDENCE_ID = /^[a-zA-Z0-9._:-]{1,128}$/;
const METRIC_ID = /^[a-z][a-z0-9_]{1,63}$/;
const SCAN_KINDS = new Set(["match", "objective", "fight", "economy"]);
const SIDES = new Set(["radiant", "dire"]);

const METRIC_LABELS: Record<string, string> = {
  duration: "Длительность матча",
  radiant_score: "Убийства Radiant",
  dire_score: "Убийства Dire",
  occurrences: "Зафиксировано событий",
  radiant_kills: "Убийства Radiant в окне",
  radiant_deaths: "Смерти Radiant в окне",
  radiant_gold_delta: "Изменение золота Radiant",
  radiant_xp_delta: "Изменение опыта Radiant",
  dire_kills: "Убийства Dire в окне",
  dire_deaths: "Смерти Dire в окне",
  dire_gold_delta: "Изменение золота Dire",
  dire_xp_delta: "Изменение опыта Dire",
  radiant_gold_advantage: "Преимущество золота Radiant",
  radiant_xp_advantage: "Преимущество опыта Radiant",
};

const KIND_LABELS: Record<ScanPreview["kind"], string> = {
  match: "Итог матча",
  objective: "Игровой объект",
  fight: "Командная драка",
  economy: "Экономика матча",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSafeInteger(value: unknown, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): value is number {
  return typeof value === "number"
    && Number.isSafeInteger(value)
    && value >= minimum
    && value <= maximum;
}

function isPlayerSlot(value: unknown): value is number {
  return isSafeInteger(value) && ((value >= 0 && value <= 4) || (value >= 128 && value <= 132));
}

function isNullableStat(value: unknown): value is number | null {
  return value === null || isSafeInteger(value);
}

function parsePlayer(value: unknown): ScanPlayer | null {
  if (!isRecord(value)
    || !isPlayerSlot(value.playerSlot)
    || !isSafeInteger(value.heroId, 1, 1024)
    || typeof value.side !== "string"
    || !SIDES.has(value.side)
    || !isNullableStat(value.kills)
    || !isNullableStat(value.deaths)
    || !isNullableStat(value.assists)) return null;

  if ((value.playerSlot < 128) !== (value.side === "radiant")) return null;
  return {
    playerSlot: value.playerSlot,
    heroId: value.heroId,
    side: value.side as ScanSide,
    kills: value.kills,
    deaths: value.deaths,
    assists: value.assists,
  };
}

function parseMetric(value: unknown): ScanMetric | null {
  if (!isRecord(value)
    || typeof value.metric !== "string"
    || !METRIC_ID.test(value.metric)
    || typeof value.value !== "number"
    || !Number.isSafeInteger(value.value)
    || typeof value.unit !== "string"
    || value.unit.length < 1
    || value.unit.length > 32) return null;
  return { metric: value.metric, value: value.value, unit: value.unit };
}

export function parseScanSuccess(value: unknown): ScanSuccessResponse | null {
  if (!isRecord(value)) return null;

  if (value.status === "choose_player") {
    if (!isRecord(value.match)
      || typeof value.match.matchId !== "string"
      || !MATCH_ID.test(value.match.matchId)
      || !isSafeInteger(value.match.durationSeconds, 1, 12 * 60 * 60)
      || !Array.isArray(value.players)
      || value.players.length !== 10) return null;
    const players = value.players.map(parsePlayer);
    if (players.some((player) => player === null)) return null;
    if (new Set(players.map((player) => player!.playerSlot)).size !== players.length) return null;
    return {
      status: "choose_player",
      match: {
        matchId: value.match.matchId,
        durationSeconds: value.match.durationSeconds,
      },
      players: players as ScanPlayer[],
    };
  }

  if (value.status !== "ready" || !isRecord(value.preview)) return null;
  const preview = value.preview;
  if (preview.schemaVersion !== "scan-preview.v1"
    || typeof preview.matchId !== "string"
    || !MATCH_ID.test(preview.matchId)
    || !isPlayerSlot(preview.playerSlot)
    || typeof preview.selectedEvidenceId !== "string"
    || !EVIDENCE_ID.test(preview.selectedEvidenceId)
    || typeof preview.kind !== "string"
    || !SCAN_KINDS.has(preview.kind)
    || !isSafeInteger(preview.atSeconds, 0, 12 * 60 * 60)
    || !(preview.team === null || (typeof preview.team === "string" && SIDES.has(preview.team)))
    || !Array.isArray(preview.metrics)
    || preview.metrics.length > 12) return null;
  const metrics = preview.metrics.map(parseMetric);
  if (metrics.some((metric) => metric === null)) return null;
  return {
    status: "ready",
    preview: {
      schemaVersion: "scan-preview.v1",
      matchId: preview.matchId,
      playerSlot: preview.playerSlot,
      selectedEvidenceId: preview.selectedEvidenceId,
      kind: preview.kind as ScanPreview["kind"],
      atSeconds: preview.atSeconds,
      team: preview.team as ScanSide | null,
      metrics: metrics as ScanMetric[],
    },
  };
}

export function parseScanError(value: unknown): ScanErrorResponse | null {
  if (!isRecord(value) || !isRecord(value.error)) return null;
  const error = value.error;
  if (typeof error.code !== "string"
    || !ERROR_CODE.test(error.code)
    || typeof error.message !== "string"
    || error.message.length < 1
    || error.message.length > 300
    || typeof error.retryable !== "boolean"
    || typeof error.requestId !== "string"
    || !REQUEST_ID.test(error.requestId)) return null;
  return {
    error: {
      code: error.code,
      message: error.message,
      retryable: error.retryable,
      requestId: error.requestId,
    },
  };
}

export function formatScanTime(seconds: number): string {
  const safeSeconds = Number.isFinite(seconds) ? Math.max(0, Math.round(seconds)) : 0;
  const minutes = Math.floor(safeSeconds / 60);
  return `${minutes}:${String(safeSeconds % 60).padStart(2, "0")}`;
}

export function formatScanStat(value: number | null): string {
  return value === null ? "—" : new Intl.NumberFormat("ru-RU").format(value);
}

export function isJsonResponseMediaType(contentType: string | null): boolean {
  if (!contentType) return false;
  return contentType.split(";", 1)[0].trim().toLowerCase() === "application/json";
}

export function scanSideLabel(side: ScanSide | null): string {
  if (side === "radiant") return "Radiant";
  if (side === "dire") return "Dire";
  return "Обе команды";
}

export function scanKindLabel(kind: ScanPreview["kind"]): string {
  return KIND_LABELS[kind];
}

export function scanMetricLabel(metric: string): string {
  return METRIC_LABELS[metric] ?? `Метрика ${metric}`;
}

export function formatScanMetricValue(metric: ScanMetric): string {
  if (metric.unit === "seconds") return formatScanTime(metric.value);
  if (metric.unit === "flag") return metric.value === 0 ? "Нет" : "Да";
  const formatted = new Intl.NumberFormat("ru-RU", {
    signDisplay: metric.unit === "gold" || metric.unit === "xp" ? "exceptZero" : "auto",
    maximumFractionDigits: 0,
  }).format(metric.value);
  if (metric.unit === "gold") return `${formatted} золота`;
  if (metric.unit === "xp") return `${formatted} опыта`;
  if (metric.unit === "gpm") return `${formatted} GPM`;
  if (metric.unit === "xpm") return `${formatted} XPM`;
  if (metric.unit === "damage") return `${formatted} урона`;
  return formatted;
}
