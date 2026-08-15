import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  ApiError,
  type Account,
  type Instrument,
  type Loan,
  type LoanStatus,
  type Position,
} from "../lib/api";
import { formatCurrency, formatNumber } from "../lib/format";
import { Card } from "../components/Card";
import { OfflineNotice } from "../components/OfflineNotice";
import { useOnlineStatus } from "../lib/online";

// spec 8.1 also wants a full amortization schedule chart and a fixed-
// rate-period countdown here — deliberately deferred (current
// balance/LTV is the number that actually matters day to day; the chart
// is a nice-to-have, not scoped into this pass).

function PhysicalAssets() {
  const { t, i18n } = useTranslation(["assets", "common", "errors"]);
  const queryClient = useQueryClient();
  const online = useOnlineStatus();

  const { data: instruments } = useQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<Instrument[]>("/api/instruments"),
  });
  const physicalInstruments = (instruments ?? []).filter(
    (i) => i.valuation_mode === "ANCHORED" || i.valuation_mode === "MODELED",
  );

  const { data: positions } = useQuery({
    queryKey: ["positions", "instrument"],
    queryFn: () => api.get<Position[]>("/api/positions?group_by=instrument"),
  });

  const [instrumentId, setInstrumentId] = useState("");
  const [anchorDate, setAnchorDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [anchorValue, setAnchorValue] = useState("");
  const [method, setMethod] = useState("purchase");
  const [error, setError] = useState<string | null>(null);

  const createAnchor = useMutation({
    mutationFn: () =>
      api.post("/api/valuations", {
        instrument_id: Number(instrumentId),
        date: anchorDate,
        value_eur: anchorValue,
        method,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["positions"] });
      setAnchorValue("");
    },
    onError: (err) =>
      setError(err instanceof ApiError ? t(`errors:${err.code}`) : t("errors:generic")),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    createAnchor.mutate();
  }

  return (
    <Card>
      <h2 className="mb-3 font-medium">{t("assets:physical.title")}</h2>
      <table className="mb-4 w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-text-muted">
            <th className="py-2 font-medium">{t("common:fields.name")}</th>
            <th className="py-2 font-medium">{t("common:fields.type")}</th>
            <th className="py-2 text-right font-medium">{t("assets:positions.value")}</th>
          </tr>
        </thead>
        <tbody>
          {physicalInstruments.length === 0 && (
            <tr>
              <td colSpan={3} className="py-3 text-text-muted">
                {t("common:status.empty")}
              </td>
            </tr>
          )}
          {physicalInstruments.map((instrument) => {
            const pos = positions?.find((p) => p.instrument_id === instrument.id);
            return (
              <tr key={instrument.id} className="border-b border-border last:border-0">
                <td className="py-2">{instrument.name}</td>
                <td className="py-2 text-text-muted">
                  {t(`assets:instruments.valuationModes.${instrument.valuation_mode}`)}
                </td>
                <td className="tnum py-2 text-right">
                  {pos?.value_eur ? formatCurrency(pos.value_eur, i18n.language) : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <h3 className="mb-2 text-sm font-medium">{t("assets:physical.newAnchor")}</h3>
      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
        <div>
          <label className="mb-1 block text-xs text-text-muted">
            {t("assets:positions.instrument")}
          </label>
          <select
            value={instrumentId}
            onChange={(e) => setInstrumentId(e.target.value)}
            required
            className="rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
          >
            <option value="" disabled>
              —
            </option>
            {physicalInstruments.map((i) => (
              <option key={i.id} value={i.id}>
                {i.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs text-text-muted">{t("common:fields.date")}</label>
          <input
            type="date"
            value={anchorDate}
            onChange={(e) => setAnchorDate(e.target.value)}
            required
            className="rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-text-muted">
            {t("assets:positions.value")}
          </label>
          <input
            value={anchorValue}
            onChange={(e) => setAnchorValue(e.target.value)}
            required
            className="w-32 rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-text-muted">
            {t("assets:physical.method")}
          </label>
          <select
            value={method}
            onChange={(e) => setMethod(e.target.value)}
            className="rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
          >
            <option value="purchase">{t("assets:physical.methods.purchase")}</option>
            <option value="appraisal">{t("assets:physical.methods.appraisal")}</option>
            <option value="trade_in">{t("assets:physical.methods.trade_in")}</option>
            <option value="other">{t("assets:physical.methods.other")}</option>
          </select>
        </div>
        <button
          type="submit"
          disabled={createAnchor.isPending || !online}
          className="rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-accent-fg disabled:opacity-50"
        >
          {t("common:actions.create")}
        </button>
      </form>
      {!online && <OfflineNotice />}
      {error && (
        <p className="mt-2 text-sm text-negative" role="alert">
          {error}
        </p>
      )}
    </Card>
  );
}

function LoanRow({ loan, houseInstrumentId }: { loan: Loan; houseInstrumentId: number | null }) {
  const { t, i18n } = useTranslation(["assets", "common"]);
  const { data: status } = useQuery({
    queryKey: ["loan-status", loan.id, houseInstrumentId],
    queryFn: () => {
      const params = houseInstrumentId
        ? `?house_instrument_id=${houseInstrumentId}`
        : "";
      return api.get<LoanStatus>(`/api/loans/${loan.id}/status${params}`);
    },
  });

  return (
    <tr className="border-b border-border last:border-0">
      <td className="py-2">#{loan.id}</td>
      <td className="tnum py-2 text-right">
        {formatCurrency(loan.principal, i18n.language)}
      </td>
      <td className="tnum py-2 text-right">
        {formatNumber(loan.rate_pct, i18n.language)}%
      </td>
      <td className="tnum py-2 text-right">
        {status ? formatCurrency(status.balance_eur, i18n.language) : "…"}
      </td>
      <td className="tnum py-2 text-right">
        {status?.ltv
          ? formatNumber(Number(status.ltv) * 100, i18n.language, { maximumFractionDigits: 1 }) +
            "%"
          : t("assets:physical.noLinkedHouse")}
      </td>
    </tr>
  );
}

function Loans() {
  const { t } = useTranslation(["assets", "common", "errors"]);
  const queryClient = useQueryClient();
  const online = useOnlineStatus();

  const { data: loans } = useQuery({
    queryKey: ["loans"],
    queryFn: () => api.get<Loan[]>("/api/loans"),
  });
  const { data: accounts } = useQuery({
    queryKey: ["accounts"],
    queryFn: () => api.get<Account[]>("/api/accounts"),
  });
  const loanAccounts = (accounts ?? []).filter((a) => a.type === "LOAN");

  // No schema link between a loan and "the" house it's secured against
  // (spec's own data model doesn't have one either) — a single-household
  // setup realistically has at most one ANCHORED (house) instrument, so
  // defaulting to the first one found is a reasonable LTV default rather
  // than building a picker UI for a one-of-one choice.
  const { data: instruments } = useQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<Instrument[]>("/api/instruments"),
  });
  const houseInstrumentId =
    instruments?.find((i) => i.valuation_mode === "ANCHORED")?.id ?? null;

  const [accountId, setAccountId] = useState("");
  const [principal, setPrincipal] = useState("");
  const [ratePct, setRatePct] = useState("");
  const [startDate, setStartDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [monthlyPayment, setMonthlyPayment] = useState("");
  const [error, setError] = useState<string | null>(null);

  const createLoan = useMutation({
    mutationFn: () =>
      api.post("/api/loans", {
        account_id: Number(accountId),
        principal,
        rate_pct: ratePct,
        start_date: startDate,
        monthly_payment: monthlyPayment,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["loans"] });
      setPrincipal("");
      setRatePct("");
      setMonthlyPayment("");
    },
    onError: (err) =>
      setError(err instanceof ApiError ? t(`errors:${err.code}`) : t("errors:generic")),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    createLoan.mutate();
  }

  return (
    <Card>
      <h2 className="mb-3 font-medium">{t("assets:loans.title")}</h2>
      <table className="mb-4 w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-text-muted">
            <th className="py-2 font-medium">{t("assets:loans.id")}</th>
            <th className="py-2 text-right font-medium">{t("assets:loans.principal")}</th>
            <th className="py-2 text-right font-medium">{t("assets:loans.rate")}</th>
            <th className="py-2 text-right font-medium">{t("assets:loans.balance")}</th>
            <th className="py-2 text-right font-medium">{t("assets:loans.ltv")}</th>
          </tr>
        </thead>
        <tbody>
          {!loans?.length && (
            <tr>
              <td colSpan={5} className="py-3 text-text-muted">
                {t("common:status.empty")}
              </td>
            </tr>
          )}
          {loans?.map((loan) => (
            <LoanRow key={loan.id} loan={loan} houseInstrumentId={houseInstrumentId} />
          ))}
        </tbody>
      </table>

      <h3 className="mb-2 text-sm font-medium">{t("assets:loans.new")}</h3>
      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
        <div>
          <label className="mb-1 block text-xs text-text-muted">
            {t("assets:positions.account")}
          </label>
          <select
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            required
            className="rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
          >
            <option value="" disabled>
              —
            </option>
            {loanAccounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs text-text-muted">
            {t("assets:loans.principal")}
          </label>
          <input
            value={principal}
            onChange={(e) => setPrincipal(e.target.value)}
            required
            className="w-28 rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-text-muted">
            {t("assets:loans.rate")} (%)
          </label>
          <input
            value={ratePct}
            onChange={(e) => setRatePct(e.target.value)}
            required
            className="w-20 rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-text-muted">{t("common:fields.date")}</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            required
            className="rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-text-muted">
            {t("assets:loans.monthlyPayment")}
          </label>
          <input
            value={monthlyPayment}
            onChange={(e) => setMonthlyPayment(e.target.value)}
            required
            className="w-28 rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
          />
        </div>
        <button
          type="submit"
          disabled={createLoan.isPending || !online}
          className="rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-accent-fg disabled:opacity-50"
        >
          {t("common:actions.create")}
        </button>
      </form>
      {!online && <OfflineNotice />}
      {error && (
        <p className="mt-2 text-sm text-negative" role="alert">
          {error}
        </p>
      )}
    </Card>
  );
}

export function Assets() {
  const { t } = useTranslation("assets");
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">{t("physical.pageTitle")}</h1>
      <PhysicalAssets />
      <Loans />
    </div>
  );
}
