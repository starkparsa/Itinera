# 2026-08-29 — Frontend restyled with Tailwind CSS v4 + shadcn/ui

**All ~350 lines of hand-written `globals.css` classes are gone, replaced by
Tailwind utility classes and shadcn/ui primitives, with a new teal palette
replacing the leftover Streamlit red -- a pure styling pass, no behavior
change.**

## Changes shipped

- `frontend/`: added Tailwind CSS v4 (`tailwindcss`, `@tailwindcss/postcss`,
  `postcss.config.mjs`) and shadcn/ui (`npx shadcn@latest init`, the
  "base-nova" preset -- generates on `@base-ui/react`, not Radix, in this
  CLI version). New `components/ui/{button,card,textarea,badge,separator,
  scroll-area,accordion,alert}.tsx`.
- Rewrote all 6 existing components (`Sidebar`, `ChatApp`, `ChatMessage`,
  `ChatInput`, `TripView`, `CalendarPushButton`) and `login/page.tsx` on
  top of Tailwind + shadcn -- same props, same state, same server-action
  calls, same gating rules (export hidden until `start_date` resolves,
  etc.). See CLAUDE.md's "UI styling" decision-log row for the full
  rationale and palette choice.
- `globals.css` rewritten: Tailwind v4 import + shadcn's generated design
  tokens, palette overridden to a teal accent (Tailwind's own teal-700/
  teal-400 oklch stops), dark mode kept `prefers-color-scheme`-driven (no
  `next-themes`, no toggle -- matches the app's original zero-JS theming).

## Bugs found & fixed

- **Font never actually applied**: `--font-sans` was never set anywhere,
  so Tailwind's `font-sans` utility (used on `<html>`) fell back to the
  browser default instead of the Geist font `layout.tsx` already loads via
  `next/font`. Fixed by pointing `--font-sans` at `--font-geist-sans` in
  `:root`; removed the now-redundant manual `font-family` on `body`.
- **Mobile layout genuinely broken, found live**: the sidebar+main flex
  row had no narrow-viewport case (pre-existing in the old CSS too, not
  introduced this session) -- confirmed via the in-app browser at 375px
  that the fixed-width sidebar pushed the entire chat panel off-screen,
  not just cramped it. Fixed with a plain CSS breakpoint (`flex-col` below
  `md`, row at/above), no JS/drawer state added.
- **Accordion prop mismatch**: first draft used Radix's `type="multiple"`
  API on shadcn's Accordion; this CLI version's underlying `@base-ui/react`
  primitive uses a boolean `multiple` prop instead. Caught by `tsc
  --noEmit`, not by inspection.

## Key learnings

- The current shadcn CLI (`shadcn@4.19`, `-d` default preset "base-nova")
  scaffolds on **`@base-ui/react`** (MUI's headless primitives), not
  Radix -- a change from what most existing shadcn docs/writeups assume.
  Its component APIs sometimes differ in real, breaking ways (e.g. the
  Accordion prop above); don't assume Radix API shape when adding a new
  shadcn component to this repo, check `components/ui/*.tsx`'s actual
  base-ui props first.
- shadcn's `init` unconditionally scaffolds a `.dark` **class**-based dark
  mode block, which does nothing unless something (`next-themes`, a manual
  toggle) actually adds a `dark` class to `<html>`. This app has neither.
  Ported those same color values into a `@media (prefers-color-scheme:
  dark)` block instead of adding a new dependency for a toggle nobody
  asked for.
- Verified visually (light, dark, desktop, mobile) via a temporary local
  route rendering the components with mock data, not the real Google
  OAuth flow -- avoids needing real credentials or touching a live account
  just to look at CSS. Deleted before finishing; never committed.

## Open items / follow-ups

- No dark/light toggle was added (by design, see above) -- if a future
  session wants a manual override, that's a real dependency addition
  (`next-themes`) and a UI control, not a copy-paste of the existing
  media-query values.
- This was a styling-only pass; no visual regression test/screenshot diff
  tooling was added, so future styling changes still rely on manual
  before/after screenshots the way this session did.
