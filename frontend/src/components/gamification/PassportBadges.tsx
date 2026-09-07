"use client";

import { useEffect, useRef } from "react";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/ui/toast";
import type { Achievement, Passport } from "@/lib/types";

// passport_service.STAMP_PALETTE names -> this app's own --stamp-* CSS
// custom properties (globals.css), not Tailwind's `dark:` utility prefix --
// this app's dark mode is OS-preference-driven via a media query, not a
// `.dark` class toggle, so `dark:` utilities never actually apply here
// (see globals.css's dark-mode block comment). Kept here, not on the
// backend, so the backend never needs to know this app's design tokens --
// it only ever names a palette entry.
const ACCENT_CLASSES: Record<string, string> = {
  indigo: "border-stamp-indigo-border bg-stamp-indigo-bg text-stamp-indigo-fg",
  copper: "border-stamp-copper-border bg-stamp-copper-bg text-stamp-copper-fg",
  teal: "border-stamp-teal-border bg-stamp-teal-bg text-stamp-teal-fg",
  amber: "border-stamp-amber-border bg-stamp-amber-bg text-stamp-amber-fg",
  rose: "border-stamp-rose-border bg-stamp-rose-bg text-stamp-rose-fg",
  violet: "border-stamp-violet-border bg-stamp-violet-bg text-stamp-violet-fg",
  emerald: "border-stamp-emerald-border bg-stamp-emerald-bg text-stamp-emerald-fg",
  sky: "border-stamp-sky-border bg-stamp-sky-bg text-stamp-sky-fg",
};

const TIER_VARIANT: Record<Achievement["tier"], "outline" | "secondary" | "default"> = {
  Common: "outline",
  Rare: "secondary",
  Epic: "default",
  Legendary: "default",
};

export default function PassportBadges({ passport }: { passport: Passport | null }) {
  const { toast } = useToast();
  // Only fire once per mount -- passport.newly_unlocked reflects the
  // single request that produced this prop; nothing re-derives it later.
  const announced = useRef(false);

  useEffect(() => {
    if (announced.current || !passport) return;
    announced.current = true;
    for (const code of passport.newly_unlocked) {
      const achievement = passport.achievements.find((a) => a.code === code);
      toast({ title: `Badge unlocked: ${achievement?.label ?? code}` });
    }
  }, [passport, toast]);

  if (!passport) {
    return <p className="text-sm text-muted-foreground">Couldn&rsquo;t load your passport.</p>;
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-4 rounded-lg border bg-muted/30 p-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Level</p>
          <p className="text-2xl font-semibold">{passport.level}</p>
        </div>
        <div className="text-sm text-muted-foreground">
          {passport.xp_points} XP · {passport.trip_count} trip{passport.trip_count === 1 ? "" : "s"} ·{" "}
          {passport.countries_visited.length} countr{passport.countries_visited.length === 1 ? "y" : "ies"}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold text-muted-foreground">Passport stamps</h3>
        {passport.stamps.length === 0 ? (
          <p className="text-sm text-muted-foreground">Plan a trip to earn your first stamp.</p>
        ) : (
          <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {passport.stamps.map((stamp) => (
              <li
                key={stamp.trip_id}
                className={`rounded-lg border p-3 text-sm font-medium ${ACCENT_CLASSES[stamp.accent] ?? ACCENT_CLASSES.indigo}`}
              >
                {stamp.destination}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold text-muted-foreground">Badges</h3>
        {passport.achievements.length === 0 ? (
          <p className="text-sm text-muted-foreground">No badges yet -- keep planning to unlock some.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {passport.achievements.map((achievement) => (
              <li key={achievement.code} className="flex items-center justify-between gap-3 rounded-lg border p-3">
                <div>
                  <p className="text-sm font-medium">{achievement.label}</p>
                  <p className="text-xs text-muted-foreground">{achievement.description}</p>
                </div>
                <Badge variant={TIER_VARIANT[achievement.tier]}>{achievement.tier}</Badge>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
