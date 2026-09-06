import { Skeleton } from "@/components/ui/skeleton";

// Route-level loading UI for the Trip Hub page's own segment -- shown
// while getTrip() resolves. Previously this mimicked the *entire* chat UI
// (header, message bubbles, sidebar) because nothing was mounted yet on
// first paint. Now that ChatShell lives in the persistent app/(chat)/
// layout.tsx and is already mounted by the time this segment suspends,
// this only needs to stand in for what this page itself contributes to
// the shell's right-panel slot -- TripHubPanel -- not the whole page.
export default function Loading() {
  return (
    <aside className="w-full shrink-0 border-t bg-muted/30 p-2 md:w-10 md:border-t-0 md:border-l" aria-hidden>
      <Skeleton className="h-8 w-8 rounded-full md:mx-auto" />
    </aside>
  );
}
