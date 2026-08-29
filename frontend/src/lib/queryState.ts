import {
  useIsRestoring,
  useQuery,
  type QueryKey,
  type UseQueryOptions,
  type UseQueryResult,
} from "@tanstack/react-query";

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
 *   const query = useCachedQuery({ queryKey: [...], queryFn: ... });
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

/**
 * `useQuery`, with one behaviour changed: a failed fetch does not erase
 * data the app already has.
 *
 * Spec 6.2 is explicit — "on start the last state renders immediately from
 * IndexedDB while a fetch runs against the Pi. If it succeeds the view
 * updates; **if it fails (away from home), the cache stands**" — and
 * "never an empty screen". TanStack does keep `data` through a failed
 * refetch, but it still flips `status` to `"error"`, and every card in
 * this app branches on `isError` *before* it looks at `data`:
 *
 *     if (isError) return <CardError />;   // <- cached data never reached
 *
 * So the moment the phone is out of the house — cellular is up, so
 * `navigator.onLine` is `true` and the fetch genuinely runs and genuinely
 * fails — every card replaced perfectly good cached numbers with "an
 * error occurred". The cache did not stand; it was rendered once and then
 * thrown away a few seconds later.
 *
 * Reporting the failure is still the right thing to do, just not *here*:
 * spec 6.2 gives that job to the persistent status strip ("as of
 * 2026-08-12, 22:31 · offline", plus the 24h tint), which is global, says
 * how old the data is rather than merely that something went wrong, and
 * doesn't cost the user the numbers they opened the app to see. `error`
 * is left populated on the result for anything that wants to say more.
 *
 * A failure with nothing to fall back on still reports as an error — that
 * is a genuine "we have nothing", not a stale reading, and a card that
 * sat on a skeleton forever instead would be worse than the truth.
 *
 * Which is the whole reason for the rule below: "nothing to fall back on"
 * must mean "never fetched", not "fetched under a key nobody asks for any
 * more".
 *
 * **A query key must not contain anything derived from the current time.**
 *
 * The persisted cache is addressed *by query key* (ADR 0005 — the query
 * cache is the offline cache). A key holding today's date changes at local
 * midnight, so the next lookup asks IndexedDB for a key that has never
 * existed: `data` is `undefined`, the fetch against an unreachable Pi
 * fails, `cacheStands` correctly says there is nothing to stand on, and
 * the card errors — while yesterday's perfectly good answer sits in
 * IndexedDB under yesterday's key, where nothing will ever look for it
 * again. With `gcTime: Infinity` (main.tsx) it is not even evicted; the
 * persisted client just grows another orphaned key-set every calendar day.
 *
 * Rolling window bounds therefore get resolved *inside* the `queryFn`,
 * where they are recomputed on every fetch anyway, and the rollover that
 * date-in-key was reaching for is enforced by
 * {@link staleTimeWithinLocalDay} instead.
 */
export function useCachedQuery<
  TQueryFnData = unknown,
  TError = Error,
  TData = TQueryFnData,
  TQueryKey extends QueryKey = QueryKey,
>(
  options: UseQueryOptions<TQueryFnData, TError, TData, TQueryKey>,
): UseQueryResult<TData, TError> {
  const result = useQuery(options);
  if (!cacheStands(result.isError, result.data)) return result;
  return {
    ...result,
    status: "success",
    isError: false,
    isSuccess: true,
    isRefetchError: false,
    // `error` deliberately survives: the query really did fail, and a
    // caller that wants to explain *why* the numbers are old should be
    // able to. Only the status flags cards branch on are rewritten.
  } as UseQueryResult<TData, TError>;
}

/**
 * Pure core of {@link useCachedQuery}: does this failed query have
 * something cached to fall back on? Split out for the same reason
 * {@link computeIsQueryLoading} is — so the rule itself has a unit test
 * without needing a DOM or a QueryClient. Components should use the hook.
 */
export function cacheStands(isError: boolean, data: unknown): boolean {
  return isError && data !== undefined;
}

/** The app-wide staleTime floor: how long any answer counts as fresh
 * before a mount/focus/reconnect will refetch it. */
export const DEFAULT_STALE_MS = 30_000;

/**
 * Milliseconds from `dataUpdatedAt` to the next *local* midnight after it.
 *
 * Built by constructing the boundary from local calendar fields rather than
 * by adding 86_400_000, so the platform resolves DST for us: on the 23-hour
 * spring-forward day the answer really is an hour shorter, and on the
 * 25-hour autumn day an hour longer.
 */
export function msUntilNextLocalDay(dataUpdatedAt: number): number {
  const d = new Date(dataUpdatedAt);
  const nextMidnight = new Date(
    d.getFullYear(),
    d.getMonth(),
    d.getDate() + 1,
    0,
    0,
    0,
    0,
  );
  return nextMidnight.getTime() - dataUpdatedAt;
}

/**
 * The default staleTime, clamped so no answer is ever considered fresh
 * across a local midnight.
 *
 * The rolling `from` bounds several queries send (`isoDaysAgo(14)`, the
 * Wealth ladder, the 180-day hero window) move at local midnight, so an
 * answer computed yesterday describes yesterday's window. Marking it stale
 * at the boundary means the next mount, window focus or reconnect refetches
 * with a freshly computed bound — which is exactly what putting the date in
 * the query key used to achieve, minus the cost of orphaning the offline
 * cache every night (see {@link useCachedQuery}).
 *
 * Stale is not empty: the old answer keeps rendering until the refetch
 * lands, and if the refetch fails the cache stands. `dataUpdatedAt === 0`
 * means nothing has ever been fetched, which is stale by definition.
 */
export function staleTimeWithinLocalDay(dataUpdatedAt: number): number {
  if (!dataUpdatedAt) return 0;
  return Math.min(DEFAULT_STALE_MS, msUntilNextLocalDay(dataUpdatedAt));
}
