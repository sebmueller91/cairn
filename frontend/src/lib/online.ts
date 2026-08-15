import { useEffect, useState } from "react";

// Offline writes are deliberately not supported (spec 6.2, ADR 0005) — a
// sync queue with conflict resolution needed once a year isn't worth the
// complexity for an agent-driven app that writes at home anyway. This is
// the one place that decision gets enforced; every form just disables
// itself based on this.
export function useOnlineStatus(): boolean {
  const [online, setOnline] = useState(navigator.onLine);

  useEffect(() => {
    const goOnline = () => setOnline(true);
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  return online;
}
