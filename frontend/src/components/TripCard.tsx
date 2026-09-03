import Link from "next/link";
import type { TripSummary } from "@/lib/types";
import { Badge } from "@/components/ui/badge";

// Falls back to a flat, palette-toned banner with the destination's
// initials whenever there's no real photo yet -- PEXELS_API_KEY unset, the
// search found nothing, or (briefly) not fetched yet. Never a broken
// image, never a fabricated one.
function initials(destination: string): string {
  const words = destination.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 3).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

const STATUS_STYLES: Record<TripSummary["status"], string> = {
  upcoming: "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-100",
  draft: "border-border bg-background text-foreground",
  completed: "border-transparent bg-muted text-muted-foreground",
};

const STATUS_LABEL: Record<TripSummary["status"], string> = {
  upcoming: "Upcoming",
  draft: "Draft",
  completed: "Completed",
};

export default function TripCard({ trip }: { trip: TripSummary }) {
  return (
    <Link
      href={`/trips/${trip.id}`}
      className="flex flex-col overflow-hidden rounded-lg border bg-card transition-colors hover:border-primary/50"
    >
      {trip.photo_url ? (
        <div className="relative h-20 overflow-hidden">
          {/* eslint-disable-next-line @next/next/no-img-element -- external, unpredictable Pexels URLs; not worth Next/Image's static-domain config for one card thumbnail */}
          <img src={trip.photo_url} alt="" className="h-full w-full object-cover" />
          {trip.photo_credit && (
            <span className="absolute right-1 bottom-0.5 rounded bg-black/40 px-1 text-[10px] text-white/90">
              Photo: {trip.photo_credit}
            </span>
          )}
        </div>
      ) : (
        <div className="flex h-20 items-center justify-center bg-primary/10">
          <span className="text-2xl font-semibold tracking-wide text-primary">{initials(trip.destination)}</span>
        </div>
      )}
      <div className="flex flex-col gap-1.5 p-3.5">
        <Badge variant="outline" className={`w-fit ${STATUS_STYLES[trip.status]}`}>
          {STATUS_LABEL[trip.status]}
        </Badge>
        <span className="text-lg font-semibold">{trip.destination}</span>
        <span className="text-sm text-muted-foreground">
          {trip.start_date ? `Starting ${trip.start_date}` : "Dates not set yet"}
        </span>
        <div className="mt-1 flex items-center justify-between text-xs text-muted-foreground">
          <span>{trip.day_count} {trip.day_count === 1 ? "day" : "days"}</span>
        </div>
      </div>
    </Link>
  );
}
