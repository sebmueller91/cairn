import { useCallback, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { useOnlineStatus } from "../lib/online";
import { formatDateTime } from "../lib/format";

const STALE_AFTER_MS = 24 * 60 * 60 * 1000;

// Rolls up the oldest dataUpdatedAt across every currently-mounted query,
// not just one endpoint — the status bar should reflect the actual data
// on screen, which may be a mix of ages once IndexedDB-cached pages are
// visited offline.
function useOldestDataUpdatedAt(): number | null {
  const queryClient = useQueryClient();
  const subscribe = useCallback(
    (onStoreChange: () => void) => queryClient.getQueryCache().subscribe(onStoreChange),
    [queryClient],
  );
  const getSnapshot = useCallback(() => {
    const mounted = queryClient
      .getQueryCache()
      .getAll()
      .filter((q) => q.getObserversCount() > 0 && q.state.dataUpdatedAt > 0);
    if (!mounted.length) return null;
    return Math.min(...mounted.map((q) => q.state.dataUpdatedAt));
  }, [queryClient]);
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

/** Compact "data as of …" status — a coloured dot plus muted text, for the shell header. */
export function FreshnessIndicator() {
  const { t, i18n } = useTranslation("common");
  const online = useOnlineStatus();
  const oldest = useOldestDataUpdatedAt();

  if (oldest == null) return null;
  const isStale = Date.now() - oldest > STALE_AFTER_MS;
  const asOf = t("status.asOf", { date: formatDateTime(new Date(oldest), i18n.language) });

  return (
    <span
      className={[
        "tnum inline-flex items-center gap-1.5 text-xs",
        isStale ? "text-warning" : "text-text-muted",
      ].join(" ")}
      title={isStale ? t("status.stale") : undefined}
    >
      <span
        aria-hidden
        className={[
          "size-1.5 shrink-0 rounded-full",
          !online ? "bg-text-muted" : isStale ? "bg-warning" : "bg-positive",
        ].join(" ")}
      />
      {asOf}
      {!online && ` · ${t("status.offline")}`}
    </span>
  );
}
