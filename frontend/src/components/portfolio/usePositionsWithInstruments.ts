import { useMemo } from "react";
import { api, type Instrument, type Position } from "../../lib/api";
import { useCachedQuery, useIsLoading } from "../../lib/queryState";

export interface PositionWithInstrument extends Position {
  instrument: Instrument | undefined;
}

/**
 * Positions (grouped by instrument) joined with their instrument row —
 * neither /api/positions nor /api/instruments carries the other's fields
 * (see Portfolio.tsx task brief), so every section that needs asset_class
 * or a display name on a position does this join. Both queries are shared
 * (same queryKey) with any other page/component reading them, so this is
 * cheap to call from more than one card.
 *
 * `isPending` folds in `useIsRestoring()` here rather than leaving each of
 * the three callers to do it themselves — during the IndexedDB cache
 * restore, TanStack forces every query's `fetchStatus` to "idle", so plain
 * `isLoading`/`isPending` reads as "done, no data" for the entire restore
 * window and every card renders its empty/error state instead of waiting.
 */
export function usePositionsWithInstruments() {
  const positions = useCachedQuery({
    queryKey: ["positions", "instrument"],
    queryFn: () => api.get<Position[]>("/api/positions?group_by=instrument"),
  });
  const instruments = useCachedQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<Instrument[]>("/api/instruments"),
  });

  const rows = useMemo<PositionWithInstrument[] | undefined>(() => {
    if (!positions.data || !instruments.data) return undefined;
    const byId = new Map(instruments.data.map((i) => [i.id, i]));
    return positions.data.map((p) => ({ ...p, instrument: byId.get(p.instrument_id) }));
  }, [positions.data, instruments.data]);

  const pending = useIsLoading(positions.isPending, instruments.isPending);

  return {
    rows,
    isPending: pending,
    isError: positions.isError || instruments.isError,
  };
}
