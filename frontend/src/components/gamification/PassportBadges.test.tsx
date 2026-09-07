import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import PassportBadges from "./PassportBadges";
import { ToastProvider } from "@/components/ui/toast";
import type { Passport } from "@/lib/types";

const EMPTY_PASSPORT: Passport = {
  level: 1,
  xp_points: 0,
  trip_count: 0,
  distinct_destinations: 0,
  countries_visited: [],
  stamps: [],
  achievements: [],
  newly_unlocked: [],
};

function renderWithToast(passport: Passport | null) {
  return render(
    <ToastProvider>
      <PassportBadges passport={passport} />
    </ToastProvider>
  );
}

describe("PassportBadges", () => {
  it("shows an empty state for a fresh account with no trips yet", () => {
    renderWithToast(EMPTY_PASSPORT);
    expect(screen.getByText("Plan a trip to earn your first stamp.")).toBeInTheDocument();
    expect(screen.getByText("No badges yet -- keep planning to unlock some.")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument(); // level
  });

  it("renders a stamp tile per trip and a badge tile per achievement", () => {
    const passport: Passport = {
      ...EMPTY_PASSPORT,
      level: 2,
      xp_points: 110,
      trip_count: 1,
      stamps: [{ trip_id: 1, destination: "Lisbon", accent: "teal", created_at: "2026-09-01T00:00:00" }],
      achievements: [
        { code: "first_trip", label: "First Trip", description: "Planned your first itinerary.", tier: "Common", earned_at: "2026-09-01T00:00:00" },
      ],
    };
    renderWithToast(passport);

    expect(screen.getByText("Lisbon")).toBeInTheDocument();
    expect(screen.getByText("First Trip")).toBeInTheDocument();
    expect(screen.getByText("Common")).toBeInTheDocument();
  });

  it("toasts once per newly unlocked code on mount", () => {
    const passport: Passport = {
      ...EMPTY_PASSPORT,
      trip_count: 1,
      achievements: [
        { code: "first_trip", label: "First Trip", description: "Planned your first itinerary.", tier: "Common", earned_at: "2026-09-01T00:00:00" },
      ],
      newly_unlocked: ["first_trip"],
    };
    renderWithToast(passport);

    expect(screen.getByText("Badge unlocked: First Trip")).toBeInTheDocument();
  });

  it("renders a graceful message when the passport failed to load", () => {
    renderWithToast(null);
    expect(screen.getByText(/Couldn.t load your passport\./)).toBeInTheDocument();
  });
});
