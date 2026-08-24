import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check } from "lucide-react";
import {
  api,
  type Instrument,
  type TaxOverviewResponse,
  type RegimeLiquidation,
  type UnrealizedTaxEstimate,
  type VorabpauschaleEntry,
} from "../../lib/api";
import { formatCurrency, formatDate, formatNumber, formatPercent } from "../../lib/format";
import { parseDecimalInput } from "../../lib/decimalInput";
import { GlassCard } from "../ui/GlassCard";
import { SegmentedControl } from "../ui/SegmentedControl";
import { ProgressArc } from "../ui/ProgressArc";
import { DataTable, type Column } from "../ui/DataTable";
import { Skeleton } from "../ui/Skeleton";
import { useIsLoading } from "../../lib/queryState";

type YearMode = "current" | "last";

const DEFAULT_ALLOWANCE = "1000";
const DEFAULT_PRIVATE_SALE_LIMIT = "1000";
const DEFAULT_PERSONAL_RATE = "42";
// Debounced separately from the raw keystrokes: the backend declares
// these Decimal query params, and firing a request on every keystroke of
// a half-typed "1.000,00" would 422 repeatedly before the user finishes.
const INPUT_DEBOUNCE_MS = 400;

/** A numeric field that only pushes a value upstream once it parses, so
 *  a half-typed amount keeps the last good figure on screen instead of
 *  blanking the card. Extracted because the tax view now has three of
 *  them (allowance, §23 limit, personal rate) with identical needs. */
function useDebouncedDecimal(initial: string) {
  const [input, setInput] = useState(initial);
  const [value, setValue] = useState(initial);
  const [invalid, setInvalid] = useState(false);

  useEffect(() => {
    const trimmed = input.trim();
    if (trimmed === "") {
      setInvalid(false);
      return;
    }
    const id = setTimeout(() => {
      const parsed = parseDecimalInput(trimmed);
      if (parsed === null) {
        setInvalid(true);
        return;
      }
      setInvalid(false);
      setValue(parsed);
    }, INPUT_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [input]);

  return { input, setInput, value, invalid };
}

function NumberField({
  label,
  hint,
  field,
  width = "w-28",
}: {
  label: string;
  hint?: string;
  field: ReturnType<typeof useDebouncedDecimal>;
  width?: string;
}) {
  const { t } = useTranslation(["tax"]);
  return (
    <div>
      <label className="mb-1 block text-xs text-text-muted" title={hint}>
        {label}
      </label>
      <input
        value={field.input}
        onChange={(e) => field.setInput(e.target.value)}
        inputMode="decimal"
        aria-invalid={field.invalid}
        className={`h-8 ${width} rounded-full border bg-bg-subtle px-3 text-xs text-text focus:outline-none focus:ring-1 ${
          field.invalid
            ? "border-negative focus:ring-negative"
            : "border-border focus:ring-accent"
        }`}
      />
      {field.invalid && <p className="mt-1 text-xs text-negative">{t("allowanceInvalid")}</p>}
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
  hint,
}: {
  label: ReactNode;
  value: ReactNode;
  tone?: "positive" | "negative";
  hint?: string;
}) {
  const toneClass =
    tone === "positive" ? "text-positive" : tone === "negative" ? "text-negative" : "";
  return (
    <div title={hint}>
      <div className="text-xs text-text-muted">{label}</div>
      <div className={`tnum sensitive mt-0.5 text-lg font-medium ${toneClass}`}>{value}</div>
    </div>
  );
}

/** One regime's leg of the liquidation, as a compact ledger. Both legs
 *  are shown even when empty — a zero here is information ("none of my
 *  tax comes from crypto"), not clutter. */
function RegimeBreakdown({
  title,
  hint,
  regime,
  lang,
}: {
  title: string;
  hint: string;
  regime: RegimeLiquidation;
  lang: string;
}) {
  const { t } = useTranslation(["tax"]);
  const line = (label: string, value: string, tone?: "positive" | "negative") => (
    <div className="flex items-baseline justify-between gap-4 py-1">
      <span className="text-xs text-text-muted">{label}</span>
      <span
        className={`tnum sensitive text-sm ${
          tone === "positive" ? "text-positive" : tone === "negative" ? "text-negative" : ""
        }`}
      >
        {formatCurrency(value, lang)}
      </span>
    </div>
  );
  return (
    <div className="rounded-card border border-border p-4">
      <h3 className="mb-2 text-sm font-medium" title={hint}>
        {title}
      </h3>
      {line(t("liquidation.grossGain"), regime.gross_gain_eur, "positive")}
      {/* losses_eur is a positive magnitude; sign it for display, but not
          when it is zero — "-0,00 €" reads as a rounding artefact. */}
      {line(
        t("liquidation.losses"),
        Number(regime.losses_eur) === 0 ? regime.losses_eur : `-${regime.losses_eur}`,
        "negative",
      )}
      {Number(regime.tax_free_gain_eur) !== 0 &&
        line(t("liquidation.taxFree"), regime.tax_free_gain_eur, "positive")}
      {line(t("liquidation.allowanceApplied"), regime.allowance_applied_eur)}
      <div className="mt-1 border-t border-border pt-1">
        {line(t("liquidation.taxable"), regime.taxable_eur)}
        {line(t("liquidation.tax"), regime.tax_eur, "negative")}
      </div>
    </div>
  );
}

function VorabpauschaleField({
  year,
  entry,
  lang,
}: {
  year: number;
  entry: VorabpauschaleEntry | null;
  lang: string;
}) {
  const { t } = useTranslation(["tax", "common"]);
  const queryClient = useQueryClient();
  const [input, setInput] = useState("");
  const [invalid, setInvalid] = useState(false);

  // Re-seed from the stored figure, keyed on the primitive value rather
  // than the `entry` object: a background refetch hands back a fresh
  // object every time, and depending on it would wipe whatever the user
  // is halfway through typing.
  const storedAmount = entry?.amount_eur ?? null;
  useEffect(() => {
    setInput(storedAmount === null ? "" : formatNumber(storedAmount, lang, { maximumFractionDigits: 2 }));
    setInvalid(false);
  }, [storedAmount, year, lang]);

  const mutation = useMutation({
    mutationFn: (amount: string) =>
      api.post<VorabpauschaleEntry>("/api/vorabpauschale", {
        year,
        amount_eur: amount,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tax"] });
    },
  });

  const submit = () => {
    const parsed = parseDecimalInput(input.trim());
    if (parsed === null) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    mutation.mutate(parsed);
  };

  return (
    <div className="flex flex-wrap items-end gap-3">
      <div>
        <label className="mb-1 block text-xs text-text-muted">
          {t("vorabpauschale.amount")}
        </label>
        <div className="flex items-center gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            inputMode="decimal"
            placeholder={t("vorabpauschale.notEntered")}
            aria-invalid={invalid}
            className={`h-8 w-36 rounded-full border bg-bg-subtle px-3 text-xs text-text focus:outline-none focus:ring-1 ${
              invalid ? "border-negative focus:ring-negative" : "border-border focus:ring-accent"
            }`}
          />
          <button
            type="button"
            onClick={submit}
            disabled={mutation.isPending}
            className="h-8 rounded-full border border-border px-3 text-xs text-text hover:bg-bg-subtle disabled:opacity-50"
          >
            {t("vorabpauschale.save")}
          </button>
          {mutation.isSuccess && !mutation.isPending && (
            <span className="flex items-center gap-1 text-xs text-positive">
              <Check className="size-3.5" aria-hidden />
              {t("vorabpauschale.saved")}
            </span>
          )}
        </div>
        {invalid && <p className="mt-1 text-xs text-negative">{t("allowanceInvalid")}</p>}
        {mutation.isError && (
          <p className="mt-1 text-xs text-negative">{t("common:status.error")}</p>
        )}
      </div>
    </div>
  );
}

export function TaxTab() {
  const { t, i18n } = useTranslation(["tax", "common"]);
  const lang = i18n.language;
  const currentYear = new Date().getFullYear();
  const [yearMode, setYearMode] = useState<YearMode>("current");
  const year = yearMode === "current" ? currentYear : currentYear - 1;

  const allowance = useDebouncedDecimal(DEFAULT_ALLOWANCE);
  const privateSaleLimit = useDebouncedDecimal(DEFAULT_PRIVATE_SALE_LIMIT);
  // Entered as whole percent because that is how anyone talks about a
  // marginal rate; the API takes a fraction.
  const personalRate = useDebouncedDecimal(DEFAULT_PERSONAL_RATE);
  const personalRateFraction = (Number(personalRate.value) / 100).toString();

  const { data: instruments } = useQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<Instrument[]>("/api/instruments"),
  });
  const instrumentName = (id: number) => instruments?.find((i) => i.id === id)?.name ?? `#${id}`;

  const { data, isPending, isError } = useQuery({
    queryKey: ["tax", year, allowance.value, privateSaleLimit.value, personalRateFraction],
    queryFn: () =>
      api.get<TaxOverviewResponse>(
        `/api/tax?year=${year}&allowance=${allowance.value}` +
          `&private_sale_limit=${privateSaleLimit.value}` +
          `&personal_tax_rate=${personalRateFraction}`,
      ),
  });
  const pending = useIsLoading(isPending);

  const allowanceEur = Number(data?.saver_allowance.allowance_eur ?? 0);
  const usedEur = Number(data?.saver_allowance.total_eur ?? 0);
  const remainingEur = Number(data?.saver_allowance.remaining_eur ?? 0);
  const usedPct = allowanceEur > 0 ? Math.min(100, (usedEur / allowanceEur) * 100) : 0;
  const arcColor = remainingEur < 0 ? "var(--negative)" : "var(--accent)";

  const liquidation = data?.liquidation;
  const totalGain = Number(liquidation?.total_unrealized_pl_eur ?? 0);
  const totalTax = Number(liquidation?.total_tax_eur ?? 0);
  const effectiveRate = totalGain > 0 ? totalTax / totalGain : 0;

  const columns: Column<UnrealizedTaxEstimate>[] = [
    {
      key: "instrument",
      header: t("common:fields.name"),
      render: (row) => instrumentName(row.instrument_id),
    },
    {
      key: "treatment",
      header: t("unrealized.treatment"),
      render: (row) => (
        <span className="rounded-full border border-border px-2 py-0.5 text-xs text-text-muted">
          {t(`unrealized.treatments.${row.tax_treatment}`)}
        </span>
      ),
    },
    {
      key: "quantity",
      header: t("common:fields.quantity"),
      align: "right",
      render: (row) => formatNumber(row.quantity, lang, { maximumFractionDigits: 8 }),
    },
    {
      key: "costBasis",
      header: t("unrealized.costBasis"),
      align: "right",
      render: (row) => (
        <span className="sensitive">{formatCurrency(row.cost_basis_eur, lang)}</span>
      ),
    },
    {
      key: "currentValue",
      header: t("unrealized.currentValue"),
      align: "right",
      render: (row) => (
        <span className="sensitive">{formatCurrency(row.current_value_eur, lang)}</span>
      ),
    },
    {
      key: "unrealizedPl",
      header: t("unrealized.unrealizedPl"),
      align: "right",
      render: (row) => (
        <span
          className={`sensitive ${
            Number(row.unrealized_pl_eur) >= 0 ? "text-positive" : "text-negative"
          }`}
        >
          {formatCurrency(row.unrealized_pl_eur, lang)}
        </span>
      ),
    },
    {
      key: "taxFreeGain",
      header: t("unrealized.taxFreeGain"),
      align: "right",
      render: (row) =>
        Number(row.tax_free_gain_eur) === 0 ? (
          <span className="text-text-muted">—</span>
        ) : (
          <span className="sensitive text-positive">
            {formatCurrency(row.tax_free_gain_eur, lang)}
          </span>
        ),
    },
    {
      key: "nextTaxFree",
      header: t("unrealized.nextTaxFree"),
      align: "right",
      render: (row) => {
        if (row.tax_treatment !== "PRIVATE_SALE") return <span className="text-text-muted">—</span>;
        return row.next_tax_free_date ? (
          <span className="text-text-muted">{formatDate(row.next_tax_free_date, lang)}</span>
        ) : (
          <span className="text-positive">{t("unrealized.fullyFree")}</span>
        );
      },
    },
    {
      key: "estimatedTax",
      header: t("unrealized.estimatedTax"),
      align: "right",
      render: (row) => (
        <span className="sensitive">{formatCurrency(row.estimated_tax_eur, lang)}</span>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      {data?.vorabpauschale_reminder && (
        <div className="rounded-card border border-warning bg-warning/10 p-4 backdrop-blur-glass md:p-5">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-warning" aria-hidden />
            <p className="text-sm">{data.vorabpauschale_reminder}</p>
          </div>
        </div>
      )}

      <GlassCard>
        <div className="mb-5 flex flex-wrap items-end gap-4">
          <div>
            <label className="mb-1 block text-xs text-text-muted">{t("year")}</label>
            <SegmentedControl
              options={[
                { value: "current" as const, label: t("thisYear") },
                { value: "last" as const, label: t("lastYear") },
              ]}
              value={yearMode}
              onChange={setYearMode}
            />
          </div>
          <NumberField
            label={t("capitalGains.allowance")}
            hint={t("capitalGains.hint")}
            field={allowance}
          />
          <NumberField
            label={t("privateSale.limit")}
            hint={t("privateSale.hint")}
            field={privateSaleLimit}
          />
          <NumberField
            label={t("privateSale.personalRate")}
            hint={t("privateSale.personalRateHint")}
            field={personalRate}
            width="w-20"
          />
        </div>

        {pending ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : isError || !data || !liquidation ? (
          <p className="text-sm text-text-muted">{t("common:status.error")}</p>
        ) : (
          <>
            <div className="mb-1 flex flex-wrap items-baseline gap-3">
              <h2 className="font-medium">{t("liquidation.title")}</h2>
              <span className="text-xs text-text-muted">
                {t("liquidation.subtitle", { date: formatDate(liquidation.as_of, lang) })}
              </span>
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Stat
                label={t("liquidation.currentValue")}
                value={formatCurrency(liquidation.total_current_value_eur, lang)}
              />
              <Stat
                label={t("liquidation.unrealized")}
                value={formatCurrency(liquidation.total_unrealized_pl_eur, lang)}
                tone={totalGain >= 0 ? "positive" : "negative"}
              />
              <Stat
                label={t("liquidation.totalTax")}
                value={
                  <>
                    {formatCurrency(liquidation.total_tax_eur, lang)}
                    {totalGain > 0 && (
                      <span className="ml-2 text-xs font-normal text-text-muted">
                        {t("liquidation.effectiveRate", {
                          pct: formatPercent(effectiveRate, lang, {
                            maximumFractionDigits: 1,
                          }),
                        })}
                      </span>
                    )}
                  </>
                }
                tone="negative"
              />
              <Stat
                label={t("liquidation.netProceeds")}
                value={formatCurrency(liquidation.net_proceeds_eur, lang)}
              />
            </div>

            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <RegimeBreakdown
                title={t("liquidation.capitalGains")}
                hint={t("capitalGains.hint")}
                regime={liquidation.capital_gains}
                lang={lang}
              />
              <RegimeBreakdown
                title={t("liquidation.privateSale")}
                hint={t("privateSale.hint")}
                regime={liquidation.private_sale}
                lang={lang}
              />
            </div>

            {liquidation.excluded_position_count > 0 && (
              <p className="mt-3 text-xs text-text-muted">
                {t("liquidation.excluded", { count: liquidation.excluded_position_count })}
              </p>
            )}
          </>
        )}
      </GlassCard>

      <div className="grid gap-6 lg:grid-cols-2">
        <GlassCard>
          <h2 className="font-medium">{t("capitalGains.title")}</h2>
          <p className="mt-1 text-xs text-text-muted">{t("capitalGains.hint")}</p>
          {pending ? (
            <div className="mt-4 flex flex-col items-center gap-4 sm:flex-row">
              <Skeleton className="size-32 shrink-0 rounded-full" />
              <div className="grid flex-1 grid-cols-2 gap-4">
                {Array.from({ length: 4 }, (_, i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            </div>
          ) : isError || !data ? (
            <p className="mt-4 text-sm text-text-muted">{t("common:status.error")}</p>
          ) : (
            <>
              <div className="mt-4 flex flex-col items-center gap-6 sm:flex-row sm:items-center">
                <ProgressArc
                  pct={usedPct}
                  color={arcColor}
                  label={formatPercent(usedPct / 100, lang, { maximumFractionDigits: 0 })}
                  sublabel={t("capitalGains.ofAllowance")}
                />
                <div className="grid flex-1 grid-cols-2 gap-4">
                  <Stat
                    label={t("capitalGains.realizedGains")}
                    value={formatCurrency(data.saver_allowance.realized_gains_eur, lang)}
                  />
                  <Stat
                    label={t("capitalGains.investmentIncome")}
                    value={formatCurrency(data.saver_allowance.investment_income_eur, lang)}
                  />
                  <Stat
                    label={t("capitalGains.vorabpauschale")}
                    value={formatCurrency(data.saver_allowance.vorabpauschale_eur, lang)}
                    hint={t("vorabpauschale.hint")}
                  />
                  <Stat
                    label={t("capitalGains.remaining")}
                    value={formatCurrency(data.saver_allowance.remaining_eur, lang)}
                    tone={remainingEur < 0 ? "negative" : "positive"}
                  />
                </div>
              </div>

              <div className="mt-5 border-t border-border pt-4">
                <h3 className="text-sm font-medium">
                  {t("vorabpauschale.title", { year })}
                </h3>
                <p className="mb-3 mt-1 text-xs text-text-muted">{t("vorabpauschale.hint")}</p>
                <VorabpauschaleField
                  year={year}
                  entry={data.vorabpauschale}
                  lang={lang}
                />
                <p className="mt-2 text-xs text-text-muted">
                  {t("vorabpauschale.yearHint", { year, prev: year - 1 })}
                </p>
              </div>
            </>
          )}
        </GlassCard>

        <GlassCard>
          <h2 className="font-medium">{t("privateSale.title")}</h2>
          <p className="mt-1 text-xs text-text-muted">{t("privateSale.hint")}</p>
          {pending ? (
            <div className="mt-4 grid grid-cols-2 gap-4">
              {Array.from({ length: 4 }, (_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : isError || !data ? (
            <p className="mt-4 text-sm text-text-muted">{t("common:status.error")}</p>
          ) : (
            <>
              <div className="mt-4 grid grid-cols-2 gap-4">
                <Stat
                  label={t("privateSale.limit")}
                  value={formatCurrency(
                    data.private_sale_allowance.exemption_limit_eur,
                    lang,
                  )}
                />
                <Stat
                  label={t("privateSale.taxableRealized")}
                  value={formatCurrency(
                    data.private_sale_allowance.realized_taxable_eur,
                    lang,
                  )}
                />
                <Stat
                  label={t("privateSale.exemptRealized")}
                  value={formatCurrency(
                    data.private_sale_allowance.realized_exempt_eur,
                    lang,
                  )}
                  tone="positive"
                  hint={t("liquidation.taxFreeHint")}
                />
                <Stat
                  label={t("privateSale.remaining")}
                  value={formatCurrency(data.private_sale_allowance.remaining_eur, lang)}
                  tone={data.private_sale_allowance.limit_exceeded ? "negative" : "positive"}
                />
              </div>
              {data.private_sale_allowance.limit_exceeded && (
                <div className="mt-4 flex items-start gap-2 rounded-card border border-warning bg-warning/10 p-3">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
                  <p className="text-xs">{t("privateSale.exceeded")}</p>
                </div>
              )}
            </>
          )}
        </GlassCard>
      </div>

      <GlassCard className="p-0">
        <div className="p-4 pb-0 md:p-5 md:pb-0">
          <h2 className="font-medium">{t("unrealized.title")}</h2>
        </div>
        {pending ? (
          <div className="p-4 md:p-5">
            <Skeleton className="h-40 w-full" />
          </div>
        ) : isError || !data ? (
          <p className="p-4 text-sm text-text-muted md:p-5">{t("common:status.error")}</p>
        ) : !data.unrealized.length ? (
          <p className="p-4 text-text-muted md:p-5">{t("common:status.empty")}</p>
        ) : (
          <DataTable
            columns={columns}
            rows={data.unrealized}
            rowKey={(row) => `${row.account_id}-${row.instrument_id}`}
            className="mt-3"
          />
        )}
      </GlassCard>

      <p className="text-xs text-text-muted">{t("disclaimer")}</p>
    </div>
  );
}
