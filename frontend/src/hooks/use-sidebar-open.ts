import { useState, useSyncExternalStore } from "react";

// Extracted from ChatShell.tsx (2026-09 maintainability review) -- fully
// self-contained, no dependency on any other concern that file owns.

const SIDEBAR_STORAGE_KEY = "itinera:sidebar-open";

// useSyncExternalStore, not useState+useEffect -- same reasoning as
// hooks/use-mobile.ts (also reading a client-only external source):
// sidesteps both the react-hooks/set-state-in-effect lint error and the
// hydration-mismatch flash that reading localStorage in a useState
// initializer would cause, since React knows to render getServerSnapshot's
// value during SSR/hydration and only switches to the real one afterward.
function subscribeSidebarStorage(onChange: () => void) {
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
}

function getSidebarStorageSnapshot() {
  try {
    return window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === "true";
  } catch {
    return false; // Private browsing / storage disabled -- just stays closed.
  }
}

// No storage to read on the server -- collapsed by default, matching the
// "nothing extra on screen until asked for it" Trip Hub v2 direction.
function getSidebarServerSnapshot() {
  return false;
}

// Collapsed by default -- "nothing extra on screen until asked for it,"
// per the Trip Hub v2 direction (decisions.md's UI styling entry). Same
// boolean drives both presentations ChatShell renders (inline column on
// desktop, an overlay Sheet on mobile) -- there's one open/closed concept,
// just two ways of rendering it depending on viewport.
//
// Persisted to localStorage as a secondary safety net (e.g. a hard
// refresh) -- ChatShell lives in a shared layout, so the toggle already
// survives normal navigation between "/" and "/trips/[tripId]" on its own.
//
// storedSidebarOpen (useSyncExternalStore above) reflects localStorage
// without needing an effect to sync it in -- sidebarOpenOverride is null
// until the user actually toggles it *this* mount, at which point it
// takes precedence. Once toggled, the override sticks even if
// storedSidebarOpen changes later (e.g. another tab writing to the same
// key) -- same "read once, then it's this session's own state" behavior
// the old useState+useEffect version had.
export function useSidebarOpen(): [boolean, (next: boolean | ((prev: boolean) => boolean)) => void] {
  const storedSidebarOpen = useSyncExternalStore(
    subscribeSidebarStorage,
    getSidebarStorageSnapshot,
    getSidebarServerSnapshot,
  );
  const [sidebarOpenOverride, setSidebarOpenOverride] = useState<boolean | null>(null);
  const sidebarOpen = sidebarOpenOverride ?? storedSidebarOpen;

  function setSidebarOpen(next: boolean | ((prev: boolean) => boolean)) {
    const value = typeof next === "function" ? next(sidebarOpen) : next;
    setSidebarOpenOverride(value);
    try {
      window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(value));
    } catch {
      // Private browsing / storage disabled -- the toggle still works
      // for this instance, it just won't survive navigation.
    }
  }

  return [sidebarOpen, setSidebarOpen];
}
