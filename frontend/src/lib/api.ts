// Every money/quantity field is a *string* on the wire (schemas.DecimalStr,
// ADR 0001) — Pydantic serializes Decimal that way specifically so a
// client can't silently get a float back via JSON.parse. Never coerce
// these to `number` for arithmetic; only for display via lib/format.ts.

export class ApiError extends Error {
  code: string;
  params: Record<string, unknown>;
  status: number;

  constructor(status: number, code: string, params: Record<string, unknown>) {
    super(code);
    this.status = status;
    this.code = code;
    this.params = params;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!response.ok) {
    let code = "generic";
    let params: Record<string, unknown> = {};
    try {
      const body = await response.json();
      if (body?.detail?.code) {
        code = body.detail.code;
        params = body.detail.params ?? {};
      }
    } catch {
      // non-JSON error body — fall through with the generic code
    }
    throw new ApiError(response.status, code, params);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

// --- Domain types (mirrors backend/app/schemas.py) ---

export type AccountType =
  | "BROKERAGE"
  | "CRYPTO_WALLET"
  | "PHYSICAL_STORAGE"
  | "REAL_ESTATE"
  | "VEHICLE"
  | "LOAN"
  | "CASH";

export interface Account {
  id: number;
  name: string;
  type: AccountType;
  currency: string;
  institution: string | null;
  opened_at: string | null;
  closed_at: string | null;
  verified_from: string | null;
  sort_order: number;
  archived: boolean;
  created_at: string;
  updated_at: string;
}

export type AssetClass =
  | "EQUITY"
  | "BOND"
  | "COMMODITY"
  | "CRYPTO"
  | "REAL_ESTATE"
  | "VEHICLE"
  | "CASH"
  | "LIABILITY";

export type ValuationMode =
  | "MARKET"
  | "ANCHORED"
  | "MODELED"
  | "AMORTIZING_LIABILITY"
  | "NOMINAL";

export interface Instrument {
  id: number;
  name: string;
  isin: string | null;
  wkn: string | null;
  ticker: string | null;
  asset_class: AssetClass;
  valuation_mode: ValuationMode;
  currency: string;
  region: string | null;
  sector: string | null;
  liquidity_tier: string | null;
  ter_pct: string | null;
  fine_weight_g: string | null;
  valuation_config: Record<string, unknown>;
  tags: string[];
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export type TransactionType =
  | "BUY"
  | "SELL"
  | "DIVIDEND"
  | "INTEREST"
  | "FEE"
  | "TAX"
  | "DEPOSIT"
  | "WITHDRAWAL"
  | "TRANSFER"
  | "SPLIT"
  | "OPENING_BALANCE"
  | "BALANCE_STATEMENT";

export interface Transaction {
  id: number;
  external_id: string;
  import_batch_id: number;
  date: string;
  date_precision: string;
  type: TransactionType;
  account_id: number;
  instrument_id: number | null;
  counter_account_id: number | null;
  quantity: string | null;
  price: string | null;
  price_mode: string;
  currency: string;
  fx_rate: string | null;
  fees: string;
  tax: string;
  amount_eur: string;
  provisional: boolean;
  voided_at: string | null;
  voided_by_batch_id: number | null;
  note: string | null;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface Position {
  account_id: number | null;
  instrument_id: number;
  quantity: string;
  cost_basis_eur: string;
  realized_pl_eur: string;
  value_eur: string | null;
  unrealized_pl_eur: string | null;
}

export interface NetWorthPoint {
  date: string;
  value_eur: string;
}

export interface Health {
  status: string;
  database: string;
  last_price_fetch: string | null;
  last_snapshot: string | null;
  last_backup: string | null;
}
