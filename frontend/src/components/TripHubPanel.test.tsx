import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import TripHubPanel from "./TripHubPanel";
import type { TripResponse } from "@/lib/types";

const EMPTY_TRIP: TripResponse = {
  trip_id: 1,
  destination: "Lisbon",
  itinerary: [],
  note: null,
  agent_context: null,
  conversation_id: null,
  reply: null,
  weather: [],
  start_date: null,
  saved_places: [],
  events: [],
};

function open() {
  fireEvent.click(screen.getByRole("button", { name: "Show trip hub" }));
}

describe("TripHubPanel", () => {
  it("shows the empty state when nothing's been fetched yet", () => {
    render(<TripHubPanel trip={EMPTY_TRIP} />);
    open();
    expect(screen.getByText("— nothing fetched yet —")).toBeInTheDocument();
  });

  it("renders an events card with count and content, hiding the empty state", () => {
    const trip: TripResponse = {
      ...EMPTY_TRIP,
      events: [
        {
          event_id: "1",
          name: "Fado Night",
          date: "2026-10-02",
          time: "20:00:00",
          venue: "Alfama Hall",
          segment: "Music",
          genre: "World",
          price_min: 15,
          price_max: 40,
          url: "https://example.com/fado-night",
        },
      ],
    };
    render(<TripHubPanel trip={trip} />);
    open();
    expect(screen.getByText("Events during your trip (1)")).toBeInTheDocument();
    expect(screen.getByText("Fado Night")).toBeInTheDocument();
    expect(screen.getByText("2026-10-02 · 20:00:00 · Alfama Hall")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Fado Night/ })).toHaveAttribute(
      "href",
      "https://example.com/fado-night"
    );
    expect(screen.queryByText("— nothing fetched yet —")).not.toBeInTheDocument();
  });

  it("hides the events card entirely when there are no events", () => {
    render(<TripHubPanel trip={EMPTY_TRIP} />);
    open();
    expect(screen.queryByText(/Events during your trip/)).not.toBeInTheDocument();
  });
});
