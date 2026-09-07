export type ScanRuntimeEnvironment = {
  SCAN_RUNTIME_ENABLED?: string;
  SCAN_RATE_LIMIT_SECRET?: string;
  DB?: unknown;
};

export type ScanRuntimeConfig = {
  flagEnabled: boolean;
  databaseConfigured: boolean;
  rateLimitSecret: string | null;
  ready: boolean;
};

const RATE_LIMIT_SECRET = /^[\x21-\x7e]{32,512}$/;

function hasD1Binding(value: unknown): boolean {
  return typeof value === "object"
    && value !== null
    && typeof (value as { prepare?: unknown }).prepare === "function";
}

/** Pure, fail-closed parser shared by the route and server-rendered UI. */
export function parseScanRuntime(runtime: ScanRuntimeEnvironment): ScanRuntimeConfig {
  const flagEnabled = runtime.SCAN_RUNTIME_ENABLED === "true";
  const rateLimitSecret = typeof runtime.SCAN_RATE_LIMIT_SECRET === "string"
    && RATE_LIMIT_SECRET.test(runtime.SCAN_RATE_LIMIT_SECRET)
    ? runtime.SCAN_RATE_LIMIT_SECRET
    : null;
  const databaseConfigured = hasD1Binding(runtime.DB);

  return {
    flagEnabled,
    databaseConfigured,
    rateLimitSecret,
    ready: flagEnabled && databaseConfigured && rateLimitSecret !== null,
  };
}
