import { Skeleton } from "@/components/ui/skeleton";

// Route-level loading UI for the Trip Hub page -- shown while getTrip()
// resolves, before ChatApp itself has even mounted (its own internal
// loading state, from ChatApp.tsx's `pending`, only covers navigation
// *within* an already-mounted chat, not this first paint). Shape echoes
// ChatApp's real layout (header bar, a couple of message bubbles, the
// right-hand data column) closely enough that the swap-in doesn't jump.
export default function Loading() {
  return (
    <div className="flex h-dvh flex-col overflow-hidden md:flex-row" aria-hidden>
      <main className="flex min-h-0 flex-1 flex-col overflow-hidden px-4 md:px-8">
        <div className="flex shrink-0 items-center justify-between gap-4 pt-6 pb-2">
          <Skeleton className="h-8 w-8 rounded-lg" />
          <Skeleton className="h-8 w-28 rounded-lg" />
        </div>
        <div className="flex min-h-0 flex-1 flex-col gap-4 py-4">
          <div className="flex justify-end">
            <Skeleton className="h-10 w-2/5 rounded-xl" />
          </div>
          <div className="flex justify-start">
            <Skeleton className="h-32 w-3/5 rounded-xl" />
          </div>
        </div>
      </main>
      <aside className="hidden w-10 shrink-0 border-l md:block">
        <Skeleton className="h-full w-full rounded-none" />
      </aside>
    </div>
  );
}
