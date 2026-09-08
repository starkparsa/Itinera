"use client";

import { useEffect } from "react";

/** Registers the static-shell service worker (public/sw.js) once the page
 * has finished loading -- deliberately after `load`, not immediately on
 * mount, so registration never competes with the chat UI's own first
 * paint/data fetches for the main thread. Renders nothing; this is pure
 * side effect, same pattern as this app would use for any other
 * fire-and-forget client-only setup. */
export function PwaRegister() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;

    const register = () => {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        // Installability is a progressive enhancement, not a feature this
        // app depends on -- a failed registration (unsupported browser,
        // blocked by an extension, etc.) shouldn't surface as an error to
        // the user or break anything else on the page.
      });
    };

    if (document.readyState === "complete") {
      register();
    } else {
      window.addEventListener("load", register);
      return () => window.removeEventListener("load", register);
    }
  }, []);

  return null;
}
