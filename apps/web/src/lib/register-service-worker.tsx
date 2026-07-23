"use client";

import { useEffect } from "react";

// Registered client-side only, and only outside dev -- a service worker
// caching hot-reloading dev assets is the kind of stale-cache confusion
// that isn't worth the app-shell benefit while iterating locally.
export function ServiceWorkerRegister() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return;
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // Best-effort: no offline shell if registration fails, nothing else breaks.
    });
  }, []);

  return null;
}
