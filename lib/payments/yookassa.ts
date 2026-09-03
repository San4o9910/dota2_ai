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

export type YooKassaPayment = {
  id: string;
  status: "pending" | "waiting_for_capture" | "succeeded" | "canceled";
  paid: boolean;
  test: boolean;
  amount: { value: string; currency: string };
  confirmation?: { type?: string; confirmation_url?: string };
  metadata?: Record<string, string>;
};

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

function authorization(credentials: YooKassaCredentials) {
  if (!/^\d{4,32}$/.test(credentials.shopId) || credentials.secretKey.length < 12) {
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

async function readPaymentResponse(response: Response): Promise<YooKassaPayment> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new YooKassaError("YooKassa returned an unreadable response", response.status);
  }

  if (!response.ok) {
    throw new YooKassaError(`YooKassa rejected the request (${response.status})`, response.status);
  }

  const payment = payload as Partial<YooKassaPayment>;
  if (!payment.id || !payment.status || !payment.amount) {
    throw new YooKassaError("YooKassa response is missing payment fields", response.status);
  }
  return payment as YooKassaPayment;
}

export async function createAnalysisPayment(
  credentials: YooKassaCredentials,
  input: AnalysisPaymentRequest,
  transport: typeof fetch = fetch,
): Promise<YooKassaPayment> {
  validateRequest(input);
  const response = await transport(API_URL, {
    method: "POST",
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
  return readPaymentResponse(response);
}

export async function getYooKassaPayment(
  credentials: YooKassaCredentials,
  paymentId: string,
  transport: typeof fetch = fetch,
): Promise<YooKassaPayment> {
  if (!PAYMENT_ID.test(paymentId)) throw new YooKassaError("paymentId is invalid");
  const response = await transport(`${API_URL}/${paymentId}`, {
    headers: { Authorization: authorization(credentials) },
  });
  return readPaymentResponse(response);
}

export function isConfirmedAnalysisPayment(
  payment: YooKassaPayment,
  expected: Pick<AnalysisPaymentRequest, "orderId" | "matchId" | "amountRub">,
) {
  return payment.status === "succeeded"
    && payment.paid === true
    && payment.amount.currency === "RUB"
    && payment.amount.value === expected.amountRub
    && payment.metadata?.order_id === expected.orderId
    && payment.metadata?.match_id === expected.matchId
    && payment.metadata?.product === "match_analysis";
}
