"use client";

import { useState } from "react";
import type { TripResponse } from "@/lib/types";
import { pushTripToCalendar } from "@/lib/backend";
import { connectGoogleCalendarAction } from "@/lib/authActions";

// Same gating rule the old .ics ExportButton used -- hidden entirely, not
// disabled, until a trip has a resolved start_date (the backend refuses to
// push otherwise). This is now the app's one export action ("Export Plan")
// -- login already requests Calendar access (see src/auth.ts), so this
// always just tries the real push first; connectGoogleCalendarAction is
// only a recovery fallback for the rare case a stored credential went
// stale (e.g. Google's 7-day refresh-token cap on an unverified/"Testing"
// OAuth app), not the common path.
export default function CalendarPushButton({ trip }: { trip: TripResponse }) {
  const [status, setStatus] = useState<"idle" | "pushing" | "done" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);

  if (!trip.start_date || !trip.trip_id) return null;
  const tripId = trip.trip_id;

  async function handleClick() {
    setStatus("pushing");
    setMessage(null);
    const result = await pushTripToCalendar(tripId);

    if (result.ok) {
      setStatus("done");
      setMessage(`Added ${result.eventsCreated} event${result.eventsCreated === 1 ? "" : "s"} to your calendar.`);
    } else if (result.needsConnection) {
      // Stored credential is missing/stale -- send through a re-consent
      // flow to get a fresh one, rather than showing a confusing error.
      await connectGoogleCalendarAction();
    } else {
      setStatus("error");
      setMessage(result.error ?? "Couldn't export to calendar.");
    }
  }

  return (
    <div className="calendar-push">
      <button className="calendar-push-button" onClick={handleClick} disabled={status === "pushing"}>
        {status === "pushing" ? "Exporting…" : "📤 Export Plan"}
      </button>
      {message && <p className={`calendar-push__message calendar-push__message--${status}`}>{message}</p>}
    </div>
  );
}
