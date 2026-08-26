import type { TripResponse } from "@/lib/types";
import { weatherIcon } from "@/lib/weatherIcon";
import CalendarPushButton from "./CalendarPushButton";

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

  return (
    <div className="trip-view">
      {trip.agent_context && (
        <div className="banner banner--success">🔎 <strong>Agent findings:</strong> {trip.agent_context}</div>
      )}
      {trip.note && <div className="banner banner--info">{trip.note}</div>}

      {dayNumbers.map((dayNumber) => {
        const weather = weatherByDay.get(dayNumber);
        return (
          <details key={dayNumber} className="day-card" open>
            <summary>Day {dayNumber}</summary>
            {weather && (
              <p className="day-weather">
                {weatherIcon(weather.condition)} High {Math.round(weather.temp_max)}°C / {Math.round(weather.temp_max_f)}°F
                {" — Low "}
                {Math.round(weather.temp_min)}°C / {Math.round(weather.temp_min_f)}°F — {weather.condition}
              </p>
            )}
            <ul>
              {(days.get(dayNumber) ?? []).map((item, idx) => (
                <li key={idx}>
                  {item.time_of_day ? <strong>{item.time_of_day}</strong> : null}
                  {item.time_of_day ? " — " : ""}
                  {item.activity}
                  {item.notes && <div className="item-notes">{item.notes}</div>}
                </li>
              ))}
            </ul>
          </details>
        );
      })}

      <div className="trip-actions">
        <CalendarPushButton trip={trip} />
      </div>
    </div>
  );
}
