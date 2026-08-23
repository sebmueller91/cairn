import { useEffect, useState, type ReactNode } from "react";
import { IsRestoringProvider, QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { restoreQueryClient, subscribeToPersist } from "./persister";

/**
 * Hand-rolled, bounded stand-in for `PersistQueryClientProvider`
 * (`@tanstack/react-query-persist-client`). That component is exactly this
 * shape internally, but awaits the IndexedDB restore with no timeout — see
 * `restoreQueryClient` in persister.ts for why that's a real bug (a restore
 * that never settles leaves the whole app permanently blank) and why it's
 * fixed by racing the restore against a timeout instead of by changing
 * anything here. This component only wires the pieces (`IsRestoringProvider`,
 * `persistQueryClientSubscribe`) around that bounded restore the same way
 * the library component wires them around its unbounded one.
 */
export function BoundedPersistProvider({
  client,
  children,
}: {
  client: QueryClient;
  children: ReactNode;
}) {
  const [isRestoring, setIsRestoring] = useState(true);

  useEffect(() => {
    let cancelled = false;
    restoreQueryClient(client).finally(() => {
      if (!cancelled) setIsRestoring(false);
    });
    return () => {
      cancelled = true;
    };
    // Restore once, on mount — same lifecycle PersistQueryClientProvider uses.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (isRestoring) return undefined;
    return subscribeToPersist(client);
  }, [isRestoring, client]);

  return (
    <QueryClientProvider client={client}>
      <IsRestoringProvider value={isRestoring}>{children}</IsRestoringProvider>
    </QueryClientProvider>
  );
}
