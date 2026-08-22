import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

/**
 * Manual "reload everything" for the shell header.
 *
 * Exists because iOS gives pull-to-refresh only to pages inside Safari's own
 * chrome, and the installed home-screen app runs `display: standalone` — so
 * the gesture that works in the Android PWA is simply absent on the iPad, and
 * force-quitting from the app switcher was the only way to escape a cache
 * that never expires on its own (ADR 0005: staleness is shown, not enforced).
 */
export function RefreshButton() {
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();
  const fetching = useIsFetching();
  const busy = fetching > 0;

  // No filter: mounted queries refetch now, and the ones sitting in IndexedDB
  // for the pages we're not on are marked stale so they refetch on mount
  // rather than handing back yesterday's numbers after a "refresh".
  const refresh = useCallback(() => {
    queryClient.invalidateQueries();
  }, [queryClient]);

  // Deliberately not gated on `navigator.onLine`: this app is LAN-only, so the
  // flag reads "online" on mobile data with the Pi unreachable, and "offline"
  // says nothing either — it would disable the button in exactly the wrong
  // situations. Let the tap through and let the failure show itself.
  return (
    <button
      type="button"
      onClick={refresh}
      disabled={busy}
      aria-busy={busy}
      title={t("actions.refresh")}
      aria-label={t("actions.refresh")}
      className={`transition-colors ${busy ? "text-accent" : "text-text-muted hover:text-text"}`}
    >
      {/* The colour swap above carries the busy state on its own, so the spin
          can stay motion-safe without leaving reduced-motion users guessing. */}
      <RefreshCw className={`size-4 ${busy ? "motion-safe:animate-spin" : ""}`} aria-hidden />
    </button>
  );
}
