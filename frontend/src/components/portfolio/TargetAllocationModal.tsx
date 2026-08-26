import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useCachedQuery } from "../../lib/queryState";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { api, ApiError } from "../../lib/api";
import { ASSET_CLASS_COLORS, assetClassLabelKey, type AssetClass } from "../../lib/assetClasses";
import { formatPercent } from "../../lib/format";
import { parseDecimalInput } from "../../lib/decimalInput";
import { useOnlineStatus } from "../../lib/online";
import { Modal } from "../ui/Modal";
import { OfflineNotice } from "../OfflineNotice";

/** Server-side rule (allocation_service.set_targets): either nothing at all,
 * or exactly 100. Mirrored here so the button can say why it is disabled
 * instead of the save failing after the fact. */
const REQUIRED_TOTAL = 100;

function sumOf(values: Record<string, string>): number | null {
  let total = 0;
  for (const raw of Object.values(values)) {
    if (raw.trim() === "") continue;
    const parsed = parseDecimalInput(raw);
    if (parsed === null) return null;
    total += Number(parsed);
  }
  return total;
}

/**
 * Editor for the target allocation — the second and last write action in the
 * UI, after the cash balance.
 *
 * `classes` comes from the drift rows rather than from ASSET_CLASSES: the
 * comparison only covers tradeable positions, so offering a target for the
 * house would invite setting one that could never be met and would read as
 * a permanent 70-point drift.
 *
 * Clearing every field is a legitimate save — it removes the targets and
 * puts the card back to showing pure current allocation.
 */
export function TargetAllocationModal({
  open,
  onClose,
  classes,
}: {
  open: boolean;
  onClose: () => void;
  classes: AssetClass[];
}) {
  const { t } = useTranslation(["portfolio", "common", "errors"]);
  const queryClient = useQueryClient();
  const online = useOnlineStatus();

  const { data: targets } = useCachedQuery({
    queryKey: ["allocation-targets"],
    queryFn: () => api.get<Record<string, string>>("/api/allocation/targets"),
  });

  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
  }, []);

  // Seed from the stored targets each time the modal opens — not on every
  // render, or a background refetch would overwrite what is being typed.
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open && !wasOpen.current) {
      const seeded: Record<string, string> = {};
      for (const cls of classes) {
        const stored = targets?.[cls];
        seeded[cls] = stored != null ? String(Number(stored)).replace(".", ",") : "";
      }
      setValues(seeded);
      setError(null);
      setSuccess(false);
    }
    wasOpen.current = open;
  }, [open, classes, targets]);

  const total = sumOf(values);
  const filled = Object.values(values).some((v) => v.trim() !== "");
  const valid = total !== null && (!filled || Math.abs(total - REQUIRED_TOTAL) < 0.005);

  const save = useMutation({
    mutationFn: () => {
      const payload: Record<string, string> = {};
      for (const [cls, raw] of Object.entries(values)) {
        if (raw.trim() === "") continue;
        const parsed = parseDecimalInput(raw);
        if (parsed === null) throw new ApiError(400, "invalid_amount", {});
        payload[cls] = parsed;
      }
      return api.put<Record<string, string>>("/api/allocation/targets", { targets: payload });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["allocation"] });
      queryClient.invalidateQueries({ queryKey: ["allocation-targets"] });
      setSuccess(true);
      setError(null);
      closeTimer.current = setTimeout(onClose, 900);
    },
    onError: (err) => {
      setSuccess(false);
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

  return (
    <Modal open={open} onClose={onClose} title={t("portfolio:targetVsActual.editTitle")}>
      {success ? (
        <div className="flex flex-col items-center gap-3 py-6 text-center">
          <span
            className="flex size-12 items-center justify-center rounded-full bg-positive/15 text-positive"
            style={{ boxShadow: "var(--glow-positive)" }}
          >
            <Check className="size-6" aria-hidden />
          </span>
          <p className="text-sm font-medium">{t("portfolio:targetVsActual.saved")}</p>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-3">
          {classes.map((cls) => (
            <div key={cls} className="flex items-center gap-3">
              <span
                aria-hidden
                className="size-2 shrink-0 rounded-full"
                style={{ backgroundColor: ASSET_CLASS_COLORS[cls] }}
              />
              <label htmlFor={`target-${cls}`} className="flex-1 truncate text-sm">
                {t(`common:${assetClassLabelKey(cls)}`)}
              </label>
              <input
                id={`target-${cls}`}
                type="text"
                inputMode="decimal"
                value={values[cls] ?? ""}
                onChange={(e) => {
                  setValues((v) => ({ ...v, [cls]: e.target.value }));
                  setError(null);
                }}
                placeholder="0"
                className="tnum w-20 rounded-md border border-border bg-bg-subtle px-2 py-1.5 text-right text-sm text-text outline-none focus:border-accent"
              />
              <span className="w-4 text-sm text-text-muted">%</span>
            </div>
          ))}

          <div className="flex items-center justify-between border-t border-border pt-3 text-sm">
            <span className="text-text-muted">{t("portfolio:targetVsActual.sum")}</span>
            <span
              className={`tnum font-medium ${
                total === null || (filled && !valid) ? "text-negative" : "text-text"
              }`}
            >
              {total === null ? "—" : formatPercent(total / 100, "de")}
            </span>
          </div>
          {filled && !valid && total !== null && (
            <p className="text-xs text-negative">
              {t("portfolio:targetVsActual.mustSum")}
            </p>
          )}
          {!filled && (
            <p className="text-xs text-text-muted">
              {t("portfolio:targetVsActual.clearHint")}
            </p>
          )}

          {!online && <OfflineNotice />}
          {error && <p className="text-sm text-negative">{error}</p>}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="rounded-full px-3 py-1.5 text-sm text-text-muted hover:text-text"
            >
              {t("common:actions.cancel")}
            </button>
            <button
              type="submit"
              disabled={!online || !valid || save.isPending}
              className="rounded-full bg-accent px-4 py-1.5 text-sm font-medium text-accent-fg disabled:opacity-40"
            >
              {t("common:actions.save")}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
