"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { TripResponse } from "@/lib/types";
import { weatherIcon } from "@/lib/weatherIcon";

// The Trip Hub v2 mockup's right-hand data column -- Weather / Flight /
// Saved Places. Flight tracking is still unbuilt entirely (no backend
// data at all), so that slot is omitted rather than shown empty; Weather
// and Saved Places both have real backing data now.
//
// Collapsed by default -- opened only on request, same principle already
// applied to the trip sidebar (ChatApp.tsx's sidebarOpen) and to each
// individual card inside the panel (nothing pre-printed before the data
// actually exists).
export default function TripHubPanel({ trip }: { trip: TripResponse }) {
  const [open, setOpen] = useState(false);
  const hasWeather = trip.weather.length > 0;
  const arrival = trip.weather[0];
  const hasSavedPlaces = trip.saved_places.length > 0;

  return (
    <aside
      className={`relative shrink-0 border-t bg-muted/30 md:border-t-0 md:border-l ${
        open ? "w-full p-4 md:w-64" : "w-full p-2 md:w-10"
      }`}
    >
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label={open ? "Hide trip hub" : "Show trip hub"}
        className="flex size-6 items-center justify-center rounded-full border bg-background text-muted-foreground hover:text-foreground md:absolute md:top-4 md:-left-3"
      >
        {open ? <ChevronRight className="size-3.5" /> : <ChevronLeft className="size-3.5" />}
      </button>

      {open ? (
        <div className="mt-8 flex flex-col gap-3 md:mt-0">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Trip hub</p>

          {hasWeather && arrival && (
            <div className="rounded-lg border bg-background p-3">
              <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Weather, arrival</p>
              <p className="mt-1 text-2xl font-semibold">
                {weatherIcon(arrival.condition)} {Math.round(arrival.temp_max)}°C
              </p>
              <p className="text-xs text-muted-foreground">
                {arrival.condition} — {Math.round(arrival.temp_min)}°–{Math.round(arrival.temp_max)}°C /{" "}
                {Math.round(arrival.temp_min_f)}°–{Math.round(arrival.temp_max_f)}°F
              </p>
            </div>
          )}

          {hasSavedPlaces && (
            <div className="rounded-lg border bg-background p-3">
              <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                Saved places ({trip.saved_places.length})
              </p>
              <ul className="mt-1.5 flex flex-col gap-1.5">
                {trip.saved_places.map((place) => (
                  <li key={place.name} className="flex items-baseline justify-between gap-2 text-sm">
                    <span className="truncate">{place.name}</span>
                    {place.rating && (
                      <span className="shrink-0 text-xs text-muted-foreground">★ {place.rating.toFixed(1)}</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {!hasWeather && !hasSavedPlaces && (
            <p className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
              — nothing fetched yet —
            </p>
          )}
        </div>
      ) : (
        <span className="hidden text-center text-[10px] font-medium tracking-widest text-muted-foreground uppercase [writing-mode:vertical-rl] md:block">
          Trip hub
        </span>
      )}
    </aside>
  );
}
