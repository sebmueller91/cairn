import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GlassCard } from "../ui/GlassCard";
import { Skeleton } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { ApiError, getEtfSplit, setEtfSplitTarget } from "../../lib/api";
import { formatCurrency, formatPercent } from "../../lib/format";
import { parseDecimalInput } from "../../lib/decimalInput";
import { useOnlineStatus } from "../../lib/online";
import { SERIES_COLORS } from "../charts/chartTheme";

const DEVELOPED_COLOR = SERIES_COLORS[0];
const EMERGING_COLOR = SERIES_COLORS[1];

/**
 * Section 5 — the developed/emerging split of the fund holdings, against a
 * target for the emerging side.
 *
 * One number is enough to express the whole plan: a 70/30 World/EM split is
 * "30% emerging", and the developed side is whatever is left. Two inputs
 * that must add to 100 would only be two ways to get it wrong.
 *
 * Every fund is weighted by its own region breakdown rather than bucketed
 * whole, which is what makes an all-world fund contribute to both sides at
 * once — and what means adding another fund never requires deciding which
 * bucket it belongs in.
 */
export function EtfSplitCard() {
  const { t, i18n } = useTranslation(["portfolio", "common", "errors"]);
  const queryClient = useQueryClient();
  const online = useOnlineStatus();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["etf-split"],
    queryFn: getEtfSplit,
  });

  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seeded = useRef(false);

  useEffect(() => {
    if (!seeded.current && data) {
      setDraft(
        data.target_emerging_pct != null
          ? String(Number(data.target_emerging_pct)).replace(".", ",")
          : "",
      );
      seeded.current = true;
    }
  }, [data]);

  const save = useMutation({
    mutationFn: () => {
      const trimmed = draft.trim();
      if (trimmed === "") return setEtfSplitTarget(null);
      const parsed = parseDecimalInput(trimmed);
      if (parsed === null) throw new ApiError(400, "invalid_amount", {});
      return setEtfSplitTarget(parsed);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["etf-split"] });
      setEditing(false);
      setError(null);
    },
    onError: (err) => {
      setError(
        err instanceof ApiError ? t(`errors:${err.code}`, err.params) : t("errors:generic"),
      );
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    save.mutate();
  }

  if (isLoading) {
    return (
      <GlassCard>
        <Skeleton className="h-5 w-56" />
        <Skeleton className="mt-4 h-3 w-full" />
        <Skeleton className="mt-4 h-24 w-full" />
      </GlassCard>
    );
  }

  if (isError || !data) {
    return (
      <GlassCard>
        <h2 className="mb-2 font-medium">{t("portfolio:etfSplit.title")}</h2>
        <p className="text-sm text-text-muted">{t("common:status.error")}</p>
      </GlassCard>
    );
  }

  if (data.emerging_pct === null) {
    return (
      <GlassCard>
        <h2 className="mb-4 font-medium">{t("portfolio:etfSplit.title")}</h2>
        <EmptyState title={t("common:status.empty")} hint={t("portfolio:etfSplit.emptyHint")} />
      </GlassCard>
    );
  }

  const emergingPct = Number(data.emerging_pct);
  const developedPct = 100 - emergingPct;
  const target = data.target_emerging_pct == null ? null : Number(data.target_emerging_pct);
  const drift = data.drift_pp == null ? null : Number(data.drift_pp);
  const money = (v: string) => formatCurrency(v, i18n.language);
  const pct = (n: number) => formatPercent(n / 100, i18n.language);

  return (
    <GlassCard>
      <div className="flex items-start justify-between gap-3">
        <h2 className="font-medium">{t("portfolio:etfSplit.title")}</h2>
        {!editing && (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="shrink-0 rounded-full border border-border px-3 py-1 text-xs font-medium text-text-muted transition-colors hover:border-accent hover:text-text"
          >
            {t("portfolio:etfSplit.editTarget")}
          </button>
        )}
      </div>

      <div className="mt-4 flex items-baseline gap-3">
        <span className="tnum text-2xl font-[650] tracking-tight">
          {pct(developedPct)} / {pct(emergingPct)}
        </span>
        {drift !== null && (
          <span
            className={`tnum text-sm font-medium ${
              Math.abs(drift) < 1 ? "text-text-muted" : drift > 0 ? "text-positive" : "text-negative"
            }`}
          >
            {drift >= 0 ? "+" : "−"}
            {formatPercent(Math.abs(drift) / 100, i18n.language)} {t("portfolio:etfSplit.vsTarget")}
          </span>
        )}
      </div>
      <div className="mt-1 text-xs text-text-muted">
        {t("portfolio:etfSplit.legend")}
        {target !== null && ` · ${t("portfolio:etfSplit.targetIs", { pct: pct(100 - target) + " / " + pct(target) })}`}
      </div>

      {/* Actual split as a bar, with the target as a marker on it — the same
          vocabulary the asset-class drift card uses. */}
      <div className="relative mt-3 h-3 w-full overflow-hidden rounded-full bg-border/60">
        <div
          className="h-full"
          style={{ width: `${developedPct}%`, backgroundColor: DEVELOPED_COLOR }}
        />
        <div
          className="absolute inset-y-0 right-0 h-full"
          style={{ width: `${emergingPct}%`, backgroundColor: EMERGING_COLOR }}
        />
        {target !== null && (
          <div
            aria-hidden
            className="absolute -top-1 -bottom-1 w-0.5 -translate-x-1/2 rounded-full bg-text"
            style={{ left: `${100 - target}%` }}
          />
        )}
      </div>

      {editing && (
        <form onSubmit={handleSubmit} className="mt-4 flex flex-wrap items-center gap-2">
          <label htmlFor="etf-em-target" className="text-sm text-text-muted">
            {t("portfolio:etfSplit.targetLabel")}
          </label>
          <input
            id="etf-em-target"
            type="text"
            inputMode="decimal"
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              setError(null);
            }}
            placeholder="30"
            className="tnum w-20 rounded-md border border-border bg-bg-subtle px-2 py-1.5 text-right text-sm outline-none focus:border-accent"
          />
          <span className="text-sm text-text-muted">%</span>
          <button
            type="submit"
            disabled={!online || save.isPending}
            className="rounded-full bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg disabled:opacity-40"
          >
            {t("common:actions.save")}
          </button>
          <button
            type="button"
            onClick={() => {
              setEditing(false);
              setError(null);
            }}
            className="rounded-full px-3 py-1.5 text-sm text-text-muted hover:text-text"
          >
            {t("common:actions.cancel")}
          </button>
          <span className="w-full text-xs text-text-muted">
            {t("portfolio:etfSplit.clearHint")}
          </span>
          {error && <p className="w-full text-sm text-negative">{error}</p>}
        </form>
      )}

      {/* Which fund contributes what — the answer to "and what about the
          other ETFs", since none of them has to be assigned by hand. */}
      <ul className="mt-5 space-y-1.5 text-sm">
        {data.rows.map((row) => (
          <li key={row.instrument_id} className="flex items-baseline gap-2">
            <span className="truncate">{row.name}</span>
            <span className="tnum sensitive ml-auto shrink-0 text-text-muted">
              {money(row.value_eur)}
            </span>
            <span className="tnum w-20 shrink-0 text-right">
              {pct(Number(row.emerging_pct))}
            </span>
          </li>
        ))}
      </ul>
      <div className="mt-1 text-right text-xs text-text-muted">
        {t("portfolio:etfSplit.emergingShareColumn")}
      </div>
    </GlassCard>
  );
}
