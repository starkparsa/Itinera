"use client";

import { useState } from "react";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { useToast } from "@/components/ui/toast";
import { ChipGroup, ChipOption } from "@/components/ui/toggle-chip";
import { updateProfile, skipOnboarding } from "@/lib/backend";
import type { Profile, ProfileUpdate } from "@/lib/types";

// Maps each duration bucket to the representative day count the backend's
// day-count inference actually uses -- "Varies" is a real, deliberate
// answer (stored as null), distinct from leaving the question untouched
// (stored as undefined, so PUT /profile's exclude_unset never touches it).
const TRIP_LENGTH_DAYS: Record<string, number | null> = {
  "Weekend (2-3 days)": 3,
  "Short trip (4-6 days)": 5,
  "Extended (1-2 weeks)": 10,
  "Slow travel (2+ weeks)": 14,
  "Varies": null,
};

const INTEREST_OPTIONS = [
  "Culture & history",
  "Food & local life",
  "Outdoors & adventure",
  "Relaxation & slow travel",
  "Nightlife & social",
  "Shopping & markets",
];

const COUNTRY_OPTIONS = ["United States", "Canada", "United Kingdom", "India", "Other"];

// Single-select chip fields: { label, value } pairs where `value` is what
// gets stored in FormState/sent to the backend -- the blank-string option
// mirrors each field's old <select>'s unselected default text.
const TRAVEL_FREQUENCY_OPTIONS = [
  { label: "Unsure", value: "" },
  { label: "Once in a while", value: "Once in a while" },
  { label: "A few times a year", value: "A few times a year" },
  { label: "Every chance I get", value: "Every chance I get" },
];

const PACE_OPTIONS = [
  { label: "Depends on the trip", value: "" },
  { label: "Leisurely", value: "Leisurely" },
  { label: "Balanced", value: "Balanced" },
  { label: "Packed", value: "Packed" },
];

const BUDGET_TIER_OPTIONS = [
  { label: "Depends", value: "" },
  { label: "Keep it affordable", value: "Keep it affordable" },
  { label: "Mid-range comfort", value: "Mid-range comfort" },
  { label: "Treat-myself trips", value: "Treat-myself trips" },
];

const TRAVEL_COMPANIONS_OPTIONS = [
  { label: "Varies", value: "" },
  { label: "Solo", value: "Solo" },
  { label: "Partner", value: "Partner" },
  { label: "Family with kids", value: "Family with kids" },
  { label: "Friends", value: "Friends" },
  { label: "Multi-generational group", value: "Multi-generational group" },
];

// "Skip this one" stores "" the same way the old <select>'s blank default
// option did, distinct from the field never being touched (which stays
// undefined and PUT /profile's exclude_unset leaves alone). Every other
// chip's value is the label itself, matching TRIP_LENGTH_DAYS's keys.
const TRIP_LENGTH_OPTIONS = [
  { label: "Skip this one", value: "" },
  ...Object.keys(TRIP_LENGTH_DAYS).map((label) => ({ label, value: label })),
];

// Mirrors backend/app/schemas.py's _PHONE_RE and MAX_PLAUSIBLE_AGE exactly
// -- client-side is a courtesy (catch it before a round trip), the backend
// validator is what's actually authoritative.
const PHONE_RE = /^\+?[0-9\s().-]{7,20}$/;
const MAX_PLAUSIBLE_AGE = 120;

// [color-scheme:light] matters specifically for the <select>s reusing this
// class: without it, a <select> in dark mode inherits the app's light text
// color, but its native dropdown popup still renders on an OS-native white
// background (color-scheme isn't inherited into that popup the way normal
// CSS is) -- unselected options end up nearly invisible, light-on-white.
// Forcing light color-scheme only on the control itself fixes the popup's
// contrast without touching the rest of the app's dark mode.
const fieldClass =
  "w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 [color-scheme:light]";

interface FormState {
  display_name: string;
  mobile_number: string;
  date_of_birth: string;
  country_region: string;
  country_other: string;
  travel_frequency: string;
  interests: string[];
  pace: string;
  budget_tier: string;
  travel_companions: string;
  trip_length_label: string;
  dietary_needs: string;
  accessibility_needs: string;
  bucket_list_countries: string;
}

// Seeds the form from whatever's already saved -- covers both first-time
// onboarding (mostly empty, display_name pre-filled from Google) and a
// later re-open (Profile -> Edit) picking up where a partial save left off.
function formFromProfile(profile: Profile): FormState {
  const lengthLabel =
    Object.entries(TRIP_LENGTH_DAYS).find(([, days]) => days === profile.typical_trip_length_days)?.[0] ?? "";
  const knownCountry = profile.country_region && COUNTRY_OPTIONS.includes(profile.country_region);
  return {
    display_name: profile.display_name ?? "",
    mobile_number: profile.mobile_number ?? "",
    date_of_birth: profile.date_of_birth ?? "",
    country_region: knownCountry ? profile.country_region! : profile.country_region ? "Other" : "",
    country_other: knownCountry ? "" : profile.country_region ?? "",
    travel_frequency: profile.travel_frequency ?? "",
    interests: profile.interests,
    pace: profile.pace ?? "",
    budget_tier: profile.budget_tier ?? "",
    travel_companions: profile.travel_companions ?? "",
    trip_length_label: lengthLabel,
    dietary_needs: profile.dietary_needs ?? "",
    accessibility_needs: profile.accessibility_needs ?? "",
    bucket_list_countries: profile.bucket_list_countries.join(", "),
  };
}

function validateAccountDetails(form: FormState): string | null {
  if (form.mobile_number && !PHONE_RE.test(form.mobile_number)) {
    return "That mobile number doesn't look right -- digits, spaces, and + only.";
  }
  if (form.date_of_birth) {
    const dob = new Date(form.date_of_birth);
    const today = new Date();
    if (dob > today) return "Date of birth can't be in the future.";
    if (today.getFullYear() - dob.getFullYear() > MAX_PLAUSIBLE_AGE) return "That date of birth doesn't look right.";
  }
  return null;
}

const STEP_TITLES = ["Account details", "Trip style", "Habits & logistics", "Goals"];

// Mounted by (chat)/layout.tsx (mode="onboarding", auto-shown once) or by
// /profile (mode="edit", opened on demand via a button) -- same component,
// two entry points, per the original design intent.
export default function OnboardingFlow({
  initialProfile,
  userEmail,
  mode = "onboarding",
  onDone,
}: {
  initialProfile: Profile;
  userEmail: string | null;
  mode?: "onboarding" | "edit";
  onDone?: () => void;
}) {
  const { toast } = useToast();
  const [open, setOpen] = useState(true);
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<FormState>(() => formFromProfile(initialProfile));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function toggleInterest(option: string) {
    setForm((f) => ({
      ...f,
      interests: f.interests.includes(option)
        ? f.interests.filter((i) => i !== option)
        : [...f.interests, option],
    }));
  }

  function close() {
    setOpen(false);
    onDone?.();
  }

  function handleContinue() {
    if (step === 1) {
      const validationError = validateAccountDetails(form);
      if (validationError) {
        setError(validationError);
        return;
      }
    }
    setError(null);
    setStep(step + 1);
  }

  async function handleSkip() {
    if (mode === "onboarding") {
      setSaving(true);
      await skipOnboarding();
    }
    close();
  }

  async function handleFinish() {
    const validationError = validateAccountDetails(form);
    if (validationError) {
      setError(validationError);
      return;
    }

    setSaving(true);
    setError(null);

    const country = form.country_region === "Other" ? form.country_other : form.country_region;
    const payload: ProfileUpdate = {
      display_name: form.display_name || undefined,
      mobile_number: form.mobile_number || undefined,
      date_of_birth: form.date_of_birth || undefined,
      country_region: country || undefined,
      travel_frequency: form.travel_frequency || undefined,
      interests: form.interests.length ? form.interests : undefined,
      pace: form.pace || undefined,
      budget_tier: form.budget_tier || undefined,
      travel_companions: form.travel_companions || undefined,
      typical_trip_length_days: form.trip_length_label ? TRIP_LENGTH_DAYS[form.trip_length_label] : undefined,
      dietary_needs: form.dietary_needs || undefined,
      accessibility_needs: form.accessibility_needs || undefined,
      bucket_list_countries: form.bucket_list_countries
        ? form.bucket_list_countries.split(",").map((s) => s.trim()).filter(Boolean)
        : undefined,
    };

    const result = await updateProfile(payload);
    setSaving(false);
    if (!result.ok) {
      setError(result.error ?? "Couldn't save your preferences -- try again.");
      return;
    }
    toast({ title: mode === "edit" ? "Preferences updated" : "Preferences saved" });
    close();
  }

  return (
    <Dialog open={open}>
      <DialogContent showCloseButton={false} className="sm:max-w-md">
        <div className="flex items-center justify-between text-xs font-medium text-muted-foreground">
          <span>{STEP_TITLES[step - 1]}</span>
          <span>Step {step} of {STEP_TITLES.length}</span>
        </div>
        <div className="flex gap-1">
          {STEP_TITLES.map((title, i) => (
            <div key={title} className={`h-1 flex-1 rounded-full ${i < step ? "bg-primary" : "bg-muted"}`} />
          ))}
        </div>

        <h2 className="text-base font-semibold">Help us plan like we know you</h2>
        <p className="text-sm text-muted-foreground">
          Every answer is optional and only shapes how your trips get planned.
        </p>

        {step === 1 && (
          <div className="flex flex-col gap-4">
            <label className="flex flex-col gap-1.5 text-sm font-medium">
              What should we call you?
              <input
                className={fieldClass}
                value={form.display_name}
                onChange={(e) => set("display_name", e.target.value)}
              />
              <span className="text-xs font-normal italic text-muted-foreground">
                Pulled from your Google sign-in -- change it anytime.
              </span>
            </label>

            {userEmail && (
              <div className="flex items-center gap-2 rounded-lg border bg-muted/50 px-2.5 py-2 text-sm">
                <span className="text-muted-foreground">Signed in as</span>
                <span className="font-medium">{userEmail}</span>
              </div>
            )}

            <div className="grid grid-cols-2 gap-3">
              <label className="flex flex-col gap-1.5 text-sm font-medium">
                Mobile number <span className="font-normal text-muted-foreground">(optional)</span>
                <input
                  className={fieldClass}
                  placeholder="+1 555 0100"
                  value={form.mobile_number}
                  onChange={(e) => set("mobile_number", e.target.value)}
                />
              </label>
              <label className="flex flex-col gap-1.5 text-sm font-medium">
                Date of birth <span className="font-normal text-muted-foreground">(optional)</span>
                <input
                  type="date"
                  className={fieldClass}
                  value={form.date_of_birth}
                  onChange={(e) => set("date_of_birth", e.target.value)}
                />
              </label>
            </div>
            <span className="-mt-2 text-xs font-normal italic text-muted-foreground">
              Kept private. Mobile is only used for trip-day reminders, once that feature exists; date of birth only
              ever informs a broad age range, never shared as-is.
            </span>

            <label className="flex flex-col gap-1.5 text-sm font-medium">
              Country / region
              <select
                className={fieldClass}
                value={form.country_region}
                onChange={(e) => set("country_region", e.target.value)}
              >
                <option value="">Select...</option>
                {COUNTRY_OPTIONS.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
            {form.country_region === "Other" && (
              <input
                className={fieldClass}
                placeholder="Type your country"
                value={form.country_other}
                onChange={(e) => set("country_other", e.target.value)}
              />
            )}
          </div>
        )}

        {step === 2 && (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5 text-sm font-medium">
              How often are you usually traveling?
              <ChipGroup legend="How often are you usually traveling?">
                {TRAVEL_FREQUENCY_OPTIONS.map(({ label, value }) => (
                  <ChipOption
                    key={label}
                    type="radio"
                    name="travel_frequency"
                    checked={form.travel_frequency === value}
                    onChange={() => set("travel_frequency", value)}
                  >
                    {label}
                  </ChipOption>
                ))}
              </ChipGroup>
            </div>

            <div className="flex flex-col gap-1.5 text-sm font-medium">
              What kind of trips light you up? (pick all that apply)
              <ChipGroup legend="What kind of trips light you up?">
                {INTEREST_OPTIONS.map((option) => (
                  <ChipOption
                    key={option}
                    type="checkbox"
                    checked={form.interests.includes(option)}
                    onChange={() => toggleInterest(option)}
                  >
                    {option}
                  </ChipOption>
                ))}
              </ChipGroup>
            </div>

            <div className="flex flex-col gap-1.5 text-sm font-medium">
              When you&rsquo;re there, what pace feels right?
              <ChipGroup legend="When you're there, what pace feels right?">
                {PACE_OPTIONS.map(({ label, value }) => (
                  <ChipOption
                    key={label}
                    type="radio"
                    name="pace"
                    checked={form.pace === value}
                    onChange={() => set("pace", value)}
                  >
                    {label}
                  </ChipOption>
                ))}
              </ChipGroup>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5 text-sm font-medium">
              What&rsquo;s your comfort zone for spending?
              <ChipGroup legend="What's your comfort zone for spending?">
                {BUDGET_TIER_OPTIONS.map(({ label, value }) => (
                  <ChipOption
                    key={label}
                    type="radio"
                    name="budget_tier"
                    checked={form.budget_tier === value}
                    onChange={() => set("budget_tier", value)}
                  >
                    {label}
                  </ChipOption>
                ))}
              </ChipGroup>
            </div>

            <div className="flex flex-col gap-1.5 text-sm font-medium">
              Who do you usually travel with?
              <ChipGroup legend="Who do you usually travel with?">
                {TRAVEL_COMPANIONS_OPTIONS.map(({ label, value }) => (
                  <ChipOption
                    key={label}
                    type="radio"
                    name="travel_companions"
                    checked={form.travel_companions === value}
                    onChange={() => set("travel_companions", value)}
                  >
                    {label}
                  </ChipOption>
                ))}
              </ChipGroup>
            </div>

            <div className="flex flex-col gap-1.5 text-sm font-medium">
              How long are your trips, typically?
              <ChipGroup legend="How long are your trips, typically?">
                {TRIP_LENGTH_OPTIONS.map(({ label, value }) => (
                  <ChipOption
                    key={label}
                    type="radio"
                    name="trip_length_label"
                    checked={form.trip_length_label === value}
                    onChange={() => set("trip_length_label", value)}
                  >
                    {label}
                  </ChipOption>
                ))}
              </ChipGroup>
            </div>

            <label className="flex flex-col gap-1.5 text-sm font-medium">
              Any food preferences or needs we should plan around?
              <Textarea
                placeholder="Vegetarian, halal, allergies, anything else"
                value={form.dietary_needs}
                onChange={(e) => set("dietary_needs", e.target.value)}
              />
              <span className="text-xs font-normal italic text-muted-foreground">
                Only used to shape restaurant &amp; day-plan suggestions -- never shared.
              </span>
            </label>
          </div>
        )}

        {step === 4 && (
          <div className="flex flex-col gap-4">
            <label className="flex flex-col gap-1.5 text-sm font-medium">
              Anything that&rsquo;ll help us plan a trip that actually works for you?
              <Textarea
                placeholder="Step-free routes, sensory-friendly pace, anything else -- optional"
                value={form.accessibility_needs}
                onChange={(e) => set("accessibility_needs", e.target.value)}
              />
              <span className="text-xs font-normal italic text-muted-foreground">
                Kept private -- only used to plan around your needs, never to limit what&rsquo;s suggested.
              </span>
            </label>

            <label className="flex flex-col gap-1.5 text-sm font-medium">
              Anywhere already on your mind?
              <input
                className={fieldClass}
                placeholder="Portugal, Japan, Peru..."
                value={form.bucket_list_countries}
                onChange={(e) => set("bucket_list_countries", e.target.value)}
              />
            </label>
          </div>
        )}

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="flex items-center justify-between pt-1">
          <Button variant="ghost" size="sm" onClick={handleSkip} disabled={saving}>
            {mode === "edit" ? "Cancel" : "Skip for now"}
          </Button>
          {step < STEP_TITLES.length ? (
            <Button size="sm" onClick={handleContinue}>
              Continue
            </Button>
          ) : (
            <Button size="sm" onClick={handleFinish} disabled={saving}>
              {saving ? "Saving..." : "Save preferences"}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
