import { Skeleton } from "@/components/ui/skeleton";

// Route-level loading UI -- shown by Next while the /trips server component
// (listTrips()) is fetching, instead of a blank flash before this. Shape
// mirrors the real page: a header block plus a card grid.
export default function Loading() {
  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col px-4 py-6 md:px-8" aria-hidden>
      <div className="flex flex-col gap-2">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-4 w-64" />
      </div>
      <div className="my-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-44 rounded-lg" />
        ))}
      </div>
    </main>
  );
}
