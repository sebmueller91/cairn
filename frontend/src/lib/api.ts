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

// Fired whenever any request comes back 401, so there's one place that
// reacts to an expired session instead of every card failing silently on
// its own (auth.tsx listens and clears the cached scope, which sends
// App.tsx back to the login screen). A dedicated EventTarget rather than
// `window` — keeps this decoupled from the DOM (testable without one) and
// from the auth module, which api.ts must not import (auth.tsx already
// imports api.ts; the other direction would be circular).
export const authEvents = new EventTarget();
export const UNAUTHORIZED_EVENT = "unauthorized";

/** Server-generation time for the exact response body object last handed
 * back by `request()`, read from the HTTP `Date` header rather than
 * derived from when the fetch happened to resolve.
 *
 * Exists because the service worker's `NetworkFirst` route (vite.config.ts)
 * can satisfy a `fetch()` from a cached response that's a week old — and
 * TanStack Query's own `dataUpdatedAt` is stamped at promise-resolution
 * time, so a stale cached body looks exactly as fresh as a live one to
 * anything reading it. A `Response` served out of the Cache API keeps the
 * `Date` header it was captured with, so it survives that fallback and
 * still names the moment the server actually generated it.
 *
 * Keyed by the parsed body's object identity (a fresh object per call, and
 * exactly the reference TanStack Query stores as `query.state.data`) rather
 * than by URL, so two in-flight requests to the same path can't clobber
 * each other's timestamp. Data that never passed through `request()` (e.g.
 * written via `setQueryData`, or hydrated from the IndexedDB persister on a
 * cold start) simply has no entry — callers should fall back to
 * `dataUpdatedAt` in that case, which is accurate for both of those.
 */
export const responseTimestamps = new WeakMap<object, number>();

function isTransientStatus(status: number): boolean {
  // 5xx (server/proxy trouble) and 0 (network failure — fetch rejects
  // before a status exists, handled by the caller) are worth one retry.
  // Any 4xx means the request itself was rejected as-is; retrying an
  // unauthenticated, forbidden, not-found, or invalid request just repeats
  // the same failure and delays the user seeing it.
  return status >= 500;
}

/** Whether a query's `retry` option should attempt again. Used as the
 * global `retry` in main.tsx so a 401/403/404/422 fails once instead of
 * twice, while a transient 5xx or network error still gets one retry. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && !isTransientStatus(error.status)) return false;
  return failureCount < 1;
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
    if (response.status === 401) {
      authEvents.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }

    let code = "generic";
    let params: Record<string, unknown> = {};
    try {
      const body = await response.json();
      const detail = body?.detail;
      if (
        detail &&
        typeof detail === "object" &&
        !Array.isArray(detail) &&
        typeof detail.code === "string"
      ) {
        // The backend's own {"code", "params"} contract.
        code = detail.code;
        params = detail.params ?? {};
      } else if (Array.isArray(detail) && detail.length > 0) {
        // FastAPI/Pydantic's own validation error shape — surfaces before
        // any endpoint handler runs (e.g. a malformed request body), so it
        // never goes through the backend's {code, params} translation and
        // has to be read here instead:
        // {"detail": [{"loc": [...], "msg": "...", "type": "..."}, ...]}
        const first = detail[0] as { loc?: unknown[] } | undefined;
        const field =
          Array.isArray(first?.loc) && first.loc.length > 0
            ? String(first.loc[first.loc.length - 1])
            : "input";
        code = "validation_error";
        params = { field };
      }
      // Any other shape (unrecognized JSON body) falls through as "generic".
    } catch {
      // Non-JSON error body — e.g. an unhandled 500's plain-text
      // "Internal Server Error" — response.json() throws. Nothing
      // structured to extract; fall through with the generic code.
    }
    throw new ApiError(response.status, code, params);
  }

  if (response.status === 204) return undefined as T;

  const data = (await response.json()) as T;
  const dateHeader = response.headers.get("date");
  const serverTime = dateHeader ? Date.parse(dateHeader) : NaN;
  if (data !== null && typeof data === "object" && !Number.isNaN(serverTime)) {
    responseTimestamps.set(data as object, serverTime);
  }
  return data;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
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
  tax_treatment: TaxTreatment | null;
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

export interface Loan {
  id: number;
  account_id: number;
  principal: string;
  rate_pct: string;
  start_date: string;
  fixed_until: string | null;
  monthly_payment: string;
  payment_day: number;
  extra_repayment_allowance_pct: string | null;
}

export interface LoanStatus {
  loan: Loan;
  balance_eur: string;
  ltv: string | null;
  house_value_eur: string | null;
}

export interface Health {
  status: string;
  database: string;
  last_price_fetch: string | null;
  last_snapshot: string | null;
  last_backup: string | null;
  last_offsite_backup: string | null;
}

export interface PerformancePoint {
  date: string;
  index_value: number;
}

export interface PerformanceResponse {
  scope: string;
  period: string;
  method: string;
  start_date: string;
  end_date: string;
  return_pct: number | null;
  curve: PerformancePoint[] | null;
  benchmark_curve: PerformancePoint[] | null;
}

export interface AttributionPeriod {
  start_date: string;
  end_date: string;
  start_value: string;
  end_value: string;
  deposits_withdrawals: string;
  income: string;
  costs: string;
  valuation_adjustments: string;
  fx_effect: string;
  market_gains_losses: string;
}

export interface AttributionResponse {
  granularity: string;
  periods: AttributionPeriod[];
}

/** GET /api/contributions — what actually went in over a window, as
 * opposed to attribution, which explains a change in wealth. */
export interface ContributionsResponse {
  start_date: string;
  end_date: string;
  /** Asset class -> net invested (purchases minus sales). Classes netting
   * to exactly zero are absent rather than present with "0". */
  by_asset_class: Record<string, string>;
  total_invested: string;
  /** Positive when loan principal fell over the window. */
  debt_repaid: string;
  net_worth_change: string;
}

export function getContributions(params: { from?: string; to?: string } = {}) {
  const query = new URLSearchParams();
  if (params.from) query.set("from", params.from);
  if (params.to) query.set("to", params.to);
  const suffix = query.toString() ? `?${query}` : "";
  return api.get<ContributionsResponse>(`/api/contributions${suffix}`);
}

export interface CpiIndexPointRead {
  date: string;
  index_value: string;
}

/** German CPI (ECB HICP), monthly. Fetched so the client can deflate a
 * *filtered* series — the server only ever deflates the whole portfolio. */
export function getCpiPoints() {
  return api.get<CpiIndexPointRead[]>("/api/cpi");
}

export interface EtfSplitRow {
  instrument_id: number;
  name: string;
  value_eur: string;
  emerging_eur: string;
  emerging_pct: string;
}

/** GET /api/look-through/etf-split — developed vs. emerging across fund
 * holdings, each fund weighted by its own region breakdown. */
export interface EtfSplitResponse {
  developed_eur: string;
  emerging_eur: string;
  total_eur: string;
  /** null when no funds are held — a share of nothing is not zero. */
  emerging_pct: string | null;
  target_emerging_pct: string | null;
  drift_pp: string | null;
  rows: EtfSplitRow[];
}

export function getEtfSplit() {
  return api.get<EtfSplitResponse>("/api/look-through/etf-split");
}

export function setEtfSplitTarget(emergingPct: string | null) {
  return api.put<EtfSplitResponse>("/api/look-through/etf-split/target", {
    emerging_pct: emergingPct,
  });
}

export interface DriftRow {
  asset_class: string;
  current_value_eur: string;
  current_pct: string;
  target_pct: string;
  drift_pp: string;
  drift_value_eur: string;
}

export interface RebalanceProposal {
  asset_class: string;
  amount_eur: string;
}

export interface AllocationResponse {
  drift: DriftRow[];
  rebalance_full: RebalanceProposal[];
  rebalance_purchases_only: RebalanceProposal[] | null;
}

export interface DataQualityIssue {
  kind: string;
  detail: string;
  instrument_id: number | null;
  instrument_name: string | null;
  account_id: number | null;
  age_days: number | null;
}

export interface DataQualityResponse {
  issues: DataQualityIssue[];
}

/** Which German tax regime a disposal falls under. CAPITAL_GAINS is
 *  §20 EStG (flat rate, holding period irrelevant); PRIVATE_SALE is §23
 *  (tax-free past the speculation period, personal rate inside it);
 *  NONE is what Cairn deliberately puts no number on. */
export type TaxTreatment = "CAPITAL_GAINS" | "PRIVATE_SALE" | "NONE";

/** §20 Sparerpauschbetrag — a true allowance, only the excess is taxed. */
export interface SaverAllowanceUsage {
  year: number;
  allowance_eur: string;
  realized_gains_eur: string;
  investment_income_eur: string;
  vorabpauschale_eur: string;
  total_eur: string;
  remaining_eur: string;
}

/** §23 Freigrenze — a cliff. `limit_exceeded` is a field of its own
 *  rather than something to infer from `remaining_eur`, because crossing
 *  it makes the *whole* gain taxable, not just the excess. */
export interface PrivateSaleAllowanceUsage {
  year: number;
  exemption_limit_eur: string;
  realized_taxable_eur: string;
  realized_exempt_eur: string;
  remaining_eur: string;
  limit_exceeded: boolean;
}

export interface RegimeLiquidation {
  gross_gain_eur: string;
  losses_eur: string;
  net_gain_eur: string;
  allowance_applied_eur: string;
  taxable_eur: string;
  tax_eur: string;
  tax_free_gain_eur: string;
}

export interface LiquidationSummary {
  as_of: string;
  total_current_value_eur: string;
  total_cost_basis_eur: string;
  total_unrealized_pl_eur: string;
  capital_gains: RegimeLiquidation;
  private_sale: RegimeLiquidation;
  total_tax_eur: string;
  net_proceeds_eur: string;
  excluded_position_count: number;
}

export interface UnrealizedTaxEstimate {
  account_id: number;
  instrument_id: number;
  tax_treatment: TaxTreatment;
  quantity: string;
  cost_basis_eur: string;
  current_value_eur: string;
  unrealized_pl_eur: string;
  /** The part of the gain sitting in lots already past the speculation
   *  period. Always "0" under §20. */
  tax_free_gain_eur: string;
  /** What a sale today would actually expose, before allowances. */
  exposed_gain_eur: string;
  tax_free_quantity: string;
  /** When the earliest still-locked lot clears the period, or null when
   *  nothing is locked. */
  next_tax_free_date: string | null;
  estimated_tax_eur: string;
}

export interface VorabpauschaleEntry {
  /** The year the amount counts against the allowance — the year it was
   *  debited, not the year it accrued for. */
  year: number;
  amount_eur: string;
  note: string | null;
  updated_at: string | null;
}

export interface TaxOverviewResponse {
  saver_allowance: SaverAllowanceUsage;
  private_sale_allowance: PrivateSaleAllowanceUsage;
  liquidation: LiquidationSummary;
  /** Already sorted by estimated tax, most owed first. */
  unrealized: UnrealizedTaxEstimate[];
  vorabpauschale: VorabpauschaleEntry | null;
  vorabpauschale_reminder: string | null;
}

export interface LookThroughRow {
  category: string;
  value_eur: string;
  /** The benchmark's weight for this category, null when none is set.
   *  A row may carry a weight with value_eur "0" — that's the useful
   *  case of holding nothing where the world market holds something. */
  benchmark_pct: string | null;
}

export interface LookThroughResponse {
  dimension: string;
  rows: LookThroughRow[];
  /** Name of the yardstick, e.g. "MSCI ACWI". Null when none is set. */
  benchmark_label: string | null;
}

export interface MilestoneResponse {
  scope: string;
  current_value_eur: string;
  next_milestone_eur: string;
  monthly_savings_eur: string;
  assumed_annual_return_pct: string;
  months_to_reach: number | null;
  estimated_date: string | null;
}

// Net worth decomposed by asset class over time (GET /api/timeseries/allocation).
// `values` is keyed by AssetClass; a missing key means 0 for that date, not
// "unknown" — the backend only emits buckets that actually had a row.
// LIABILITY, when present, is negative (loans reduce net worth).
export interface AllocationTimeseriesPoint {
  date: string;
  values: Record<string, string>;
}

export function getAllocationTimeseries(params: {
  from?: string;
  to?: string;
  granularity?: "day" | "week" | "month";
}): Promise<AllocationTimeseriesPoint[]> {
  const query = new URLSearchParams();
  if (params.from) query.set("from", params.from);
  if (params.to) query.set("to", params.to);
  if (params.granularity) query.set("granularity", params.granularity);
  const qs = query.toString();
  return api.get<AllocationTimeseriesPoint[]>(
    `/api/timeseries/allocation${qs ? `?${qs}` : ""}`,
  );
}

export function getHealth(): Promise<Health> {
  return api.get<Health>("/api/health");
}
