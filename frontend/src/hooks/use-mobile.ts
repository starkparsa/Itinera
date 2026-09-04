import * as React from "react"

// 768px matches Tailwind's `md` breakpoint, already used everywhere else in
// this codebase for the mobile/desktop split (e.g. Sidebar.tsx, ChatApp.tsx).
const MOBILE_BREAKPOINT = 768
const QUERY = `(max-width: ${MOBILE_BREAKPOINT - 1}px)`

// useSyncExternalStore, not useState+useEffect -- subscribing to an
// external, mutable source (the viewport) is exactly what it's for, and it
// sidesteps the extra render-then-correct flicker (and the
// react-hooks/set-state-in-effect lint error) that setting state from
// inside the effect body would otherwise need.
function subscribe(onChange: () => void) {
  const mql = window.matchMedia(QUERY)
  mql.addEventListener("change", onChange)
  return () => mql.removeEventListener("change", onChange)
}

function getSnapshot() {
  return window.matchMedia(QUERY).matches
}

// No viewport to measure on the server -- default to desktop, same
// server-safe fallback the previous implementation's initial `undefined`
// (coerced through `!!`) produced.
function getServerSnapshot() {
  return false
}

export function useIsMobile() {
  return React.useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
}
