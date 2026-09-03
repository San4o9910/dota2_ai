export type PaidProductCode = "single_analysis" | "coach_30_days";

export type BillingProduct = {
  code: PaidProductCode;
  name: string;
  shortName: string;
  priceKopecks: number;
  analyses: number;
  coachQuestions: number;
  durationDays: number | null;
  description: string;
  features: string[];
};

export const FREE_TRIAL = {
  code: "free_trial" as const,
  name: "Первый разбор",
  priceKopecks: 0,
  analyses: 1,
  coachQuestions: 5,
  description: "Один полный разбор после первого входа в NARMA VISION.",
};

export const BILLING_CATALOG: Record<PaidProductCode, BillingProduct> = {
  single_analysis: {
    code: "single_analysis",
    name: "Разбор матча",
    shortName: "Разовый",
    priceKopecks: 29_900,
    analyses: 1,
    coachQuestions: 10,
    durationDays: null,
    description: "Полный AI-разбор одного матча без подписки.",
    features: [
      "Драфт, лайнинг, мид- и лейт-гейм",
      "Карта решений, вижен, объекты и перемещения",
      "Баланс золота и опыта перед каждой дракой",
      "Персональный план тренировки",
      "10 вопросов AI-тренеру по матчу",
    ],
  },
  coach_30_days: {
    code: "coach_30_days",
    name: "AI-тренер на 30 дней",
    shortName: "Тренер",
    priceKopecks: 79_900,
    analyses: 8,
    coachQuestions: 40,
    durationDays: 30,
    description: "Два глубоких разбора в неделю с историей прогресса.",
    features: [
      "8 полных AI-разборов за 30 дней",
      "История матчей и сравнение ошибок",
      "Прогресс по пяти навыкам и четырём стадиям",
      "40 вопросов AI-тренеру",
      "Повторное открытие разбора без списания кредита",
    ],
  },
};

export const PAID_PRODUCTS = Object.values(BILLING_CATALOG);

export function isPaidProductCode(value: unknown): value is PaidProductCode {
  return typeof value === "string"
    && Object.prototype.hasOwnProperty.call(BILLING_CATALOG, value);
}

export function formatRubles(priceKopecks: number): string {
  if (!Number.isSafeInteger(priceKopecks) || priceKopecks < 0) {
    throw new Error("priceKopecks must be a non-negative safe integer");
  }
  return `${(priceKopecks / 100).toLocaleString("ru-RU", {
    maximumFractionDigits: 0,
  })} ₽`;
}

export function yookassaAmount(priceKopecks: number): string {
  if (!Number.isSafeInteger(priceKopecks) || priceKopecks <= 0) {
    throw new Error("priceKopecks must be a positive safe integer");
  }
  return (priceKopecks / 100).toFixed(2);
}
