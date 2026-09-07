export type AnalysisRuntimeEnvironment = {
  ANALYSIS_RUNTIME_ENABLED?: string;
  ANALYSIS_FULFILLMENT_ENABLED?: string;
  OPENAI_API_KEY?: string;
  OPENAI_MODEL?: string;
  OPENAI_ALLOWED_MODELS?: string;
};

export type AnalysisRuntimeConfig = {
  acceptingJobs: boolean;
  fulfillmentReady: boolean;
  apiKey: string | null;
  model: string | null;
  allowedModels: readonly string[];
};

const MODEL = /^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$/;

function enabled(value: string | undefined) {
  return value === "true";
}

function parseAllowedModels(value: string | undefined): readonly string[] {
  if (!value || value.length > 2_048) return [];
  const models = value.split(",").map((item) => item.trim());
  if (models.length > 20 || models.some((item) => !MODEL.test(item))) return [];
  return [...new Set(models)];
}

function parseApiKey(value: string | undefined): string | null {
  if (
    !value
    || value.length < 20
    || value.length > 512
    || value.trim() !== value
    || /[\x00-\x20\x7f]/.test(value)
  ) return null;
  return value;
}

export function parseAnalysisRuntime(
  runtime: AnalysisRuntimeEnvironment,
): AnalysisRuntimeConfig {
  const acceptingJobs = enabled(runtime.ANALYSIS_RUNTIME_ENABLED);
  const apiKey = parseApiKey(runtime.OPENAI_API_KEY);
  const model = runtime.OPENAI_MODEL && MODEL.test(runtime.OPENAI_MODEL)
    ? runtime.OPENAI_MODEL
    : null;
  const allowedModels = parseAllowedModels(runtime.OPENAI_ALLOWED_MODELS);
  const fulfillmentReady = acceptingJobs
    && enabled(runtime.ANALYSIS_FULFILLMENT_ENABLED)
    && apiKey !== null
    && model !== null
    && allowedModels.includes(model);

  return { acceptingJobs: fulfillmentReady, fulfillmentReady, apiKey, model, allowedModels };
}

