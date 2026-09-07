import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import OnboardingFlow from "./OnboardingFlow";
import { ToastProvider } from "@/components/ui/toast";
import { updateProfile, skipOnboarding } from "@/lib/backend";
import type { Profile } from "@/lib/types";

vi.mock("@/lib/backend", () => ({
  updateProfile: vi.fn(),
  skipOnboarding: vi.fn(),
}));

const EMPTY_PROFILE: Profile = {
  display_name: null,
  mobile_number: null,
  date_of_birth: null,
  country_region: null,
  travel_frequency: null,
  pace: null,
  budget_tier: null,
  interests: [],
  travel_companions: null,
  typical_trip_length_days: null,
  dietary_needs: null,
  accessibility_needs: null,
  bucket_list_countries: [],
  additional_preferences: null,
  onboarding_completed_at: null,
  onboarding_skipped_at: null,
};

function renderFlow(props: Partial<React.ComponentProps<typeof OnboardingFlow>> = {}) {
  return render(
    <ToastProvider>
      <OnboardingFlow initialProfile={EMPTY_PROFILE} userEmail="maya@example.com" {...props} />
    </ToastProvider>
  );
}

function continueButton() {
  return screen.getByRole("button", { name: "Continue" });
}

beforeEach(() => {
  vi.mocked(updateProfile).mockReset();
  vi.mocked(skipOnboarding).mockReset();
  vi.mocked(updateProfile).mockResolvedValue({ ok: true, data: EMPTY_PROFILE });
  vi.mocked(skipOnboarding).mockResolvedValue({ ok: true, data: EMPTY_PROFILE });
});

describe("OnboardingFlow", () => {
  it("opens on Account details, prefilled from the profile", () => {
    renderFlow({ initialProfile: { ...EMPTY_PROFILE, display_name: "Jordan" } });
    expect(screen.getByText("Step 1 of 4")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Jordan")).toBeInTheDocument();
    expect(screen.getByText("maya@example.com")).toBeInTheDocument();
  });

  it("every remaining select/date field forces a light color-scheme, so its native popup stays readable in dark mode", () => {
    // Regression guard: without this, a <select>/date input in dark mode
    // inherits the app's light text color while its native popup still
    // renders on an OS-native white background -- unselected options end up
    // light-on-white, nearly invisible (a real bug, caught by inspection).
    // Most fields are chips now (Feature 1) and don't need this fix at all
    // (no native popup involved) -- country_region (still a <select>, a
    // deliberate choice) and date_of_birth are what's left to guard.
    renderFlow();
    const country = document.querySelector("select") as HTMLSelectElement;
    expect(country).toBeInTheDocument();
    expect(country.className).toContain("[color-scheme:light]");
    const dob = document.querySelector('input[type="date"]') as HTMLInputElement;
    expect(dob.className).toContain("[color-scheme:light]");
  });

  it("single-select chip fields render as real radios, wired to the same setter as before", async () => {
    renderFlow();
    fireEvent.click(continueButton()); // step 1 -> 2
    fireEvent.click(screen.getByRole("radio", { name: "Leisurely" }));

    fireEvent.click(continueButton()); // 2 -> 3
    fireEvent.click(continueButton()); // 3 -> 4
    fireEvent.click(screen.getByRole("button", { name: "Save preferences" }));

    await waitFor(() => expect(updateProfile).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(updateProfile).mock.calls[0][0];
    expect(payload.pace).toBe("Leisurely");
  });

  it("blocks Continue on an invalid mobile number", () => {
    renderFlow();
    fireEvent.change(screen.getByPlaceholderText("+1 555 0100"), { target: { value: "not a phone" } });
    fireEvent.click(continueButton());
    expect(screen.getByText(/doesn't look right/)).toBeInTheDocument();
    expect(screen.getByText("Step 1 of 4")).toBeInTheDocument(); // still on step 1
  });

  it("blocks Continue on a future date of birth", () => {
    renderFlow();
    const dobInput = document.querySelector('input[type="date"]') as HTMLInputElement;
    fireEvent.change(dobInput, { target: { value: "2999-01-01" } });
    fireEvent.click(continueButton());
    expect(screen.getByText(/can't be in the future/)).toBeInTheDocument();
  });

  it("advances through all 4 steps and saves the full payload", async () => {
    renderFlow();

    fireEvent.click(continueButton()); // step 1 -> 2 (no account fields set, valid)
    expect(screen.getByText("Step 2 of 4")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Food & local life"));

    fireEvent.click(continueButton()); // 2 -> 3
    expect(screen.getByText("Step 3 of 4")).toBeInTheDocument();

    fireEvent.click(continueButton()); // 3 -> 4
    expect(screen.getByText("Step 4 of 4")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save preferences" }));

    await waitFor(() => expect(updateProfile).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(updateProfile).mock.calls[0][0];
    expect(payload.interests).toEqual(["Food & local life"]);
  });

  it("Skip for now calls skipOnboarding and closes the dialog", async () => {
    renderFlow();
    fireEvent.click(screen.getByRole("button", { name: "Skip for now" }));
    await waitFor(() => expect(skipOnboarding).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("Step 1 of 4")).not.toBeInTheDocument();
  });

  it("edit mode shows Cancel instead of Skip, and never calls skipOnboarding", async () => {
    const onDone = vi.fn();
    renderFlow({ mode: "edit", onDone });
    expect(screen.queryByText("Skip for now")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(skipOnboarding).not.toHaveBeenCalled();
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("shows an inline error and stays open when the save fails", async () => {
    vi.mocked(updateProfile).mockResolvedValue({ ok: false, error: "Backend returned 500" });
    renderFlow();
    fireEvent.click(continueButton());
    fireEvent.click(continueButton());
    fireEvent.click(continueButton());
    fireEvent.click(screen.getByRole("button", { name: "Save preferences" }));
    await waitFor(() => expect(screen.getByText("Backend returned 500")).toBeInTheDocument());
    expect(screen.getByText("Step 4 of 4")).toBeInTheDocument();
  });
});
