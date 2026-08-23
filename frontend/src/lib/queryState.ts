import { useIsRestoring } from "@tanstack/react-query";

/**
 * THE fix for "some elements can not load" on a cold start.
 *
 * Do not use `query.isLoading` to decide whether a card should still show
 * a loading state. It is wrong for the entire IndexedDB restore window:
 *
 * - `PersistQueryClientProvider` sets `isRestoring = true` and renders
 *   `children` *immediately* — it does not wait for the restore to finish.
 * - While restoring, TanStack's query observer force-reports
 *   `fetchStatus: "idle"` (i.e. `isFetching: false`), because it doesn't
 *   yet know whether IndexedDB holds data for this query or not.
 * - `isLoading` is defined as `isPending && isFetching`. With `isFetching`
 *   pinned to `false`, `isLoading` is `false` too — even though `data` is
 *   still `undefined` and nothing has actually been decided yet.
 *
 * So for the whole restore window every mounted query reports
 * `{ data: undefined, isLoading: false, isError: false }`, and any card
 * that branches on `isLoading` falls straight through to its empty state
 * and flashes it before the real (possibly cached) data appears a moment
 * later. `pages/Wealth.tsx` avoids this by gating on `isPending` instead,
 * which stays accurate throughout — this hook generalises that.
 *
 * Usage:
 *   const query = useQuery({ queryKey: [...], queryFn: ... });
 *   const stillLoading = useIsQueryLoading(query);
 *   if (stillLoading) return <CardSkeleton />;
 *   if (query.isError) return <CardError />;
 *   if (!query.data) return <CardEmpty />;
 *   return <CardContent data={query.data} />;
 */
export function useIsQueryLoading(query: { isPending: boolean }): boolean {
  const isRestoring = useIsRestoring();
  return computeIsQueryLoading(isRestoring, query.isPending);
}

/**
 * The same rule for callers that already have the `isPending` booleans to
 * hand — including cards that wait on several queries at once, where the
 * card is still loading until every one of them has settled.
 *
 *   const pending = useIsLoading(positionsPending, loansPending);
 */
export function useIsLoading(...pending: boolean[]): boolean {
  const isRestoring = useIsRestoring();
  return computeIsQueryLoading(isRestoring, pending.some(Boolean));
}

/**
 * Pure core of {@link useIsQueryLoading}, split out only so the boolean
 * logic itself has a unit test independent of React/TanStack context.
 * Components should use the hook, not this directly.
 */
export function computeIsQueryLoading(isRestoring: boolean, isPending: boolean): boolean {
  return isRestoring || isPending;
}
