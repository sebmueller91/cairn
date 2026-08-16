import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Instrument, type Position } from "../../lib/api";

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
 */
export function usePositionsWithInstruments() {
  const positions = useQuery({
    queryKey: ["positions", "instrument"],
    queryFn: () => api.get<Position[]>("/api/positions?group_by=instrument"),
  });
  const instruments = useQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<Instrument[]>("/api/instruments"),
  });

  const rows = useMemo<PositionWithInstrument[] | undefined>(() => {
    if (!positions.data || !instruments.data) return undefined;
    const byId = new Map(instruments.data.map((i) => [i.id, i]));
    return positions.data.map((p) => ({ ...p, instrument: byId.get(p.instrument_id) }));
  }, [positions.data, instruments.data]);

  return {
    rows,
    isLoading: positions.isLoading || instruments.isLoading,
    isError: positions.isError || instruments.isError,
  };
}
