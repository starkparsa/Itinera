import type { TripResponse } from "@/lib/types";
import { weatherIcon } from "@/lib/weatherIcon";
import CalendarPushButton from "./CalendarPushButton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";

// Port of streamlit_app.py::render_trip().
export default function TripView({ trip }: { trip: TripResponse }) {
  const days = new Map<number, TripResponse["itinerary"]>();
  for (const item of trip.itinerary) {
    const bucket = days.get(item.day_number) ?? [];
    bucket.push(item);
    days.set(item.day_number, bucket);
  }

  const weatherByDay = new Map(trip.weather.map((w) => [w.day_number, w]));
  const dayNumbers = Array.from(days.keys()).sort((a, b) => a - b);
  // Every day starts expanded, same as the old <details open> markup.
  const dayValues = dayNumbers.map((n) => String(n));

  return (
    <div className="mt-2 flex flex-col gap-2">
      {trip.agent_context && (
        <Alert className="border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-100">
          <AlertDescription className="text-inherit">
            🔎 <strong>Agent findings:</strong> {trip.agent_context}
          </AlertDescription>
        </Alert>
      )}
      {trip.note && (
        <Alert className="border-sky-200 bg-sky-50 text-sky-900 dark:border-sky-900 dark:bg-sky-950 dark:text-sky-100">
          <AlertDescription className="text-inherit">{trip.note}</AlertDescription>
        </Alert>
      )}

      <Accordion multiple defaultValue={dayValues} className="flex flex-col gap-2">
        {dayNumbers.map((dayNumber) => {
          const weather = weatherByDay.get(dayNumber);
          return (
            <AccordionItem
              key={dayNumber}
              value={String(dayNumber)}
              className="not-last:border-b-0 rounded-lg border bg-background px-3"
            >
              <AccordionTrigger className="hover:no-underline">Day {dayNumber}</AccordionTrigger>
              <AccordionContent>
                {weather && (
                  <Badge
                    variant="secondary"
                    className="mb-2 h-auto whitespace-normal px-2 py-1 text-xs font-normal"
                  >
                    {weatherIcon(weather.condition)} High {Math.round(weather.temp_max)}°C /{" "}
                    {Math.round(weather.temp_max_f)}°F — Low {Math.round(weather.temp_min)}°C /{" "}
                    {Math.round(weather.temp_min_f)}°F — {weather.condition}
                  </Badge>
                )}
                <ul className="flex list-disc flex-col gap-2 pl-5">
                  {(days.get(dayNumber) ?? []).map((item, idx) => (
                    <li key={idx} className="text-sm leading-relaxed">
                      {item.time_of_day ? <strong>{item.time_of_day}</strong> : null}
                      {item.time_of_day ? " — " : ""}
                      {item.activity}
                      {item.notes && <div className="text-xs text-muted-foreground">{item.notes}</div>}
                    </li>
                  ))}
                </ul>
              </AccordionContent>
            </AccordionItem>
          );
        })}
      </Accordion>

      <div className="flex flex-wrap items-start gap-2">
        <CalendarPushButton trip={trip} />
      </div>
    </div>
  );
}
