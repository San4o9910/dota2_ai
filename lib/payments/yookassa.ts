import { isJsonContentType } from "@/lib/security/content-type";

export type YooKassaCredentials = {
  shopId: string;
  secretKey: string;
};

export type AnalysisPaymentRequest = {
  orderId: string;
  matchId: string;
  amountRub: string;
  returnUrl: string;
};

export type CheckoutPaymentRequest = {
  orderId: string;
  productCode: string;
  description: string;
  matchId?: string;
  amountRub: string;
  returnUrl: string;
};

export type YooKassaPayment = {
  id: string;
  status: "pending" | "waiting_for_capture" | "succeeded" | "canceled";
  paid: boolean;
  test: boolean;
  amount: { value: string; currency: string };
  confirmation?: { type?: string; confirmation_url?: string };
  metadata?: Record<string, string>;
};

export type YooKassaPaymentMode = "test" | "live";

export class YooKassaError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "YooKassaError";
  }
}

const API_URL = "https://api.yookassa.ru/v3/payments";
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const MATCH_ID = /^\d{8,12}$/;
const MONEY = /^\d{1,7}\.\d{2}$/;
const PAYMENT_ID = /^[0-9a-z-]{8,64}$/i;
const PRODUCT_CODE = /^[a-z][a-z0-9_]{2,63}$/;
const REQUEST_TIMEOUT_MS = 12_000;
const MAX_RESPONSE_BYTES = 64 * 1024;
const PAYMENT_STATUSES = new Set(["pending", "waiting_for_capture", "succeeded", "canceled"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function authorization(credentials: YooKassaCredentials) {
  if (
    !/^\d{4,32}$/.test(credentials.shopId)
    || !/^[\x21-\x7e]{12,256}$/.test(credentials.secretKey)
  ) {
    throw new YooKassaError("YooKassa credentials are not configured");
  }
  return `Basic ${btoa(`${credentials.shopId}:${credentials.secretKey}`)}`;
}

function validateRequest(input: AnalysisPaymentRequest) {
  if (!UUID_V4.test(input.orderId)) throw new YooKassaError("orderId must be a UUID v4");
  if (!MATCH_ID.test(input.matchId)) throw new YooKassaError("matchId is invalid");
  if (!MONEY.test(input.amountRub) || Number(input.amountRub) <= 0) {
    throw new YooKassaError("amountRub must be a positive RUB amount with two decimals");
  }

  let returnUrl: URL;
  try {
    returnUrl = new URL(input.returnUrl);
  } catch {
    throw new YooKassaError("returnUrl must be an absolute URL");
  }
  if (returnUrl.protocol !== "https:") throw new YooKassaError("returnUrl must use HTTPS");
}

function validateCheckoutRequest(input: CheckoutPaymentRequest) {
  if (!UUID_V4.test(input.orderId)) throw new YooKassaError("orderId must be a UUID v4");
  if (!PRODUCT_CODE.test(input.productCode)) throw new YooKassaError("productCode is invalid");
  if (!input.description.trim() || input.description.length > 128) {
    throw new YooKassaError("description must contain 1 to 128 characters");
  }
  if (input.matchId !== undefined && !MATCH_ID.test(input.matchId)) {
    throw new YooKassaError("matchId is invalid");
  }
  if (!MONEY.test(input.amountRub) || Number(input.amountRub) <= 0) {
    throw new YooKassaError("amountRub must be a positive RUB amount with two decimals");
  }

  let returnUrl: URL;
  try {
    returnUrl = new URL(input.returnUrl);
  } catch {
    throw new YooKassaError("returnUrl must be an absolute URL");
  }
  if (returnUrl.protocol !== "https:") throw new YooKassaError("returnUrl must use HTTPS");
}

async function readBoundedResponse(response: Response) {
  const declaredLength = response.headers.get("content-length");
  if (declaredLength && Number(declaredLength) > MAX_RESPONSE_BYTES) {
    throw new YooKassaError("YooKassa response exceeds the size limit", response.status);
  }

  if (!response.body) return "";
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let bytes = 0;
  let body = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    bytes += value.byteLength;
    if (bytes > MAX_RESPONSE_BYTES) {
      await reader.cancel();
      throw new YooKassaError("YooKassa response exceeds the size limit", response.status);
    }
    body += decoder.decode(value, { stream: true });
  }
  return body + decoder.decode();
}

function parsePayment(payload: unknown, status: number): YooKassaPayment {
  if (!isRecord(payload)) {
    throw new YooKassaError("YooKassa response must be an object", status);
  }
  const amount = payload.amount;
  if (
    typeof payload.id !== "string"
    || !PAYMENT_ID.test(payload.id)
    || typeof payload.status !== "string"
    || !PAYMENT_STATUSES.has(payload.status)
    || typeof payload.paid !== "boolean"
    || typeof payload.test !== "boolean"
    || !isRecord(amount)
    || typeof amount.value !== "string"
    || !MONEY.test(amount.value)
    || typeof amount.currency !== "string"
    || !/^[A-Z]{3}$/.test(amount.currency)
  ) {
    throw new YooKassaError("YooKassa response has invalid payment fields", status);
  }

  let confirmation: YooKassaPayment["confirmation"];
  if (payload.confirmation !== undefined) {
    if (!isRecord(payload.confirmation)) {
      throw new YooKassaError("YooKassa confirmation is invalid", status);
    }
    const type = payload.confirmation.type;
    const confirmationUrl = payload.confirmation.confirmation_url;
    if (
      (type !== undefined && (typeof type !== "string" || type.length > 64))
      || (confirmationUrl !== undefined
        && (typeof confirmationUrl !== "string"
          || confirmationUrl.length > 2048
          || !confirmationUrl.startsWith("https://")))
    ) {
      throw new YooKassaError("YooKassa confirmation is invalid", status);
    }
    confirmation = {
      type: type as string | undefined,
      confirmation_url: confirmationUrl as string | undefined,
    };
  }

  let metadata: Record<string, string> | undefined;
  if (payload.metadata !== undefined) {
    if (!isRecord(payload.metadata)) {
      throw new YooKassaError("YooKassa metadata is invalid", status);
    }
    metadata = {};
    for (const [key, value] of Object.entries(payload.metadata)) {
      if (
        !/^[a-z0-9_]{1,64}$/i.test(key)
        || typeof value !== "string"
        || value.length > 512
      ) {
        throw new YooKassaError("YooKassa metadata is invalid", status);
      }
      metadata[key] = value;
    }
  }

  return {
    id: payload.id,
    status: payload.status as YooKassaPayment["status"],
    paid: payload.paid,
    test: payload.test,
    amount: { value: amount.value, currency: amount.currency },
    confirmation,
    metadata,
  };
}

async function readPaymentResponse(response: Response): Promise<YooKassaPayment> {
  if (!isJsonContentType(response.headers.get("content-type"))) {
    throw new YooKassaError("YooKassa returned a non-JSON response", response.status);
  }
  const body = await readBoundedResponse(response);
  let payload: unknown;
  try {
    payload = JSON.parse(body);
  } catch {
    throw new YooKassaError("YooKassa returned an unreadable response", response.status);
  }

  if (!response.ok) {
    throw new YooKassaError(`YooKassa rejected the request (${response.status})`, response.status);
  }

  return parsePayment(payload, response.status);
}

async function requestPayment(
  transport: typeof fetch,
  url: string,
  init: RequestInit,
) {
  try {
    return await readPaymentResponse(await transport(url, init));
  } catch (error) {
    if (error instanceof YooKassaError) throw error;
    const timedOut = error instanceof Error
      && ["AbortError", "TimeoutError"].includes(error.name);
    throw new YooKassaError(
      timedOut ? "YooKassa request timed out" : "YooKassa request failed",
    );
  }
}

export async function createAnalysisPayment(
  credentials: YooKassaCredentials,
  input: AnalysisPaymentRequest,
  transport: typeof fetch = fetch,
): Promise<YooKassaPayment> {
  validateRequest(input);
  return requestPayment(transport, API_URL, {
    method: "POST",
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    headers: {
      Authorization: authorization(credentials),
      "Content-Type": "application/json",
      "Idempotence-Key": input.orderId,
    },
    body: JSON.stringify({
      amount: { value: input.amountRub, currency: "RUB" },
      capture: true,
      confirmation: { type: "redirect", return_url: input.returnUrl },
      description: `Разбор матча Dota 2 ${input.matchId}`,
      metadata: {
        order_id: input.orderId,
        match_id: input.matchId,
        product: "match_analysis",
      },
    }),
  });
}

export async function createCheckoutPayment(
  credentials: YooKassaCredentials,
  input: CheckoutPaymentRequest,
  transport: typeof fetch = fetch,
): Promise<YooKassaPayment> {
  validateCheckoutRequest(input);
  const metadata: Record<string, string> = {
    order_id: input.orderId,
    product_code: input.productCode,
  };
  if (input.matchId) metadata.match_id = input.matchId;

  return requestPayment(transport, API_URL, {
    method: "POST",
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    headers: {
      Authorization: authorization(credentials),
      "Content-Type": "application/json",
      "Idempotence-Key": input.orderId,
    },
    body: JSON.stringify({
      amount: { value: input.amountRub, currency: "RUB" },
      capture: true,
      confirmation: { type: "redirect", return_url: input.returnUrl },
      description: input.description,
      metadata,
    }),
  });
}

export async function getYooKassaPayment(
  credentials: YooKassaCredentials,
  paymentId: string,
  transport: typeof fetch = fetch,
): Promise<YooKassaPayment> {
  if (!PAYMENT_ID.test(paymentId)) throw new YooKassaError("paymentId is invalid");
  return requestPayment(transport, `${API_URL}/${paymentId}`, {
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    headers: { Authorization: authorization(credentials) },
  });
}

export function isConfirmedAnalysisPayment(
  payment: YooKassaPayment,
  expected: Pick<AnalysisPaymentRequest, "orderId" | "matchId" | "amountRub">,
  paymentMode: YooKassaPaymentMode,
) {
  return payment.status === "succeeded"
    && payment.paid === true
    && paymentMatchesMode(payment, paymentMode)
    && payment.amount.currency === "RUB"
    && payment.amount.value === expected.amountRub
    && payment.metadata?.order_id === expected.orderId
    && payment.metadata?.match_id === expected.matchId
    && payment.metadata?.product === "match_analysis";
}

export function isConfirmedCheckoutPayment(
  payment: YooKassaPayment,
  expected: Pick<
    CheckoutPaymentRequest,
    "orderId" | "productCode" | "matchId" | "amountRub"
  >,
  paymentMode: YooKassaPaymentMode,
) {
  return payment.status === "succeeded"
    && payment.paid === true
    && checkoutPaymentMatchesOrder(payment, expected, paymentMode);
}

/** Verifies immutable order identity for every provider state, before redirect. */
export function checkoutPaymentMatchesOrder(
  payment: YooKassaPayment,
  expected: Pick<
    CheckoutPaymentRequest,
    "orderId" | "productCode" | "matchId" | "amountRub"
  >,
  paymentMode: YooKassaPaymentMode,
) {
  return paymentMatchesMode(payment, paymentMode)
    && payment.amount.currency === "RUB"
    && payment.amount.value === expected.amountRub
    && payment.metadata?.order_id === expected.orderId
    && payment.metadata?.product_code === expected.productCode
    && payment.metadata?.match_id === expected.matchId;
}

export function paymentMatchesMode(
  payment: Pick<YooKassaPayment, "test">,
  paymentMode: YooKassaPaymentMode,
) {
  return payment.test === (paymentMode === "test");
}
