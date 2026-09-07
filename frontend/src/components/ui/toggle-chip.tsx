import type { ReactNode } from "react";
import { cva } from "class-variance-authority";

// Styling mirrors badge.tsx's badgeVariants (rounded-4xl pill, same size
// scale) but this is an interactive control, not a display-only Badge --
// built on a real <input type="checkbox"|"radio"> rather than Badge's
// non-interactive useRender/mergeProps span, so keyboard/screen-reader
// behavior (Space/Enter toggling, role, checked state announcement) comes
// from the browser for free instead of being reimplemented. The input is
// visually hidden (sr-only) as the styled <span>'s previous sibling, so
// Tailwind's peer-* selectors can style the span off the input's real
// :checked/:focus-visible state.
const chipVariants = cva(
  "inline-flex h-8 w-fit shrink-0 cursor-pointer items-center justify-center rounded-4xl border border-input px-3 text-sm font-medium whitespace-nowrap transition-colors select-none peer-checked:border-transparent peer-checked:bg-primary peer-checked:text-primary-foreground peer-hover:not-peer-checked:bg-muted peer-focus-visible:ring-3 peer-focus-visible:ring-ring/50"
);

/**
 * A single selectable chip, backed by a real (visually-hidden) native
 * <input type="checkbox"|"radio">. Use `type="radio"` with a shared `name`
 * inside a ChipGroup for single-select fields (replacing a plain <select>),
 * or `type="checkbox"` for multi-select fields (replacing a checkbox list).
 */
export function ChipOption({
  type,
  name,
  checked,
  onChange,
  children,
}: {
  type: "checkbox" | "radio";
  name?: string;
  checked: boolean;
  onChange: () => void;
  children: ReactNode;
}) {
  return (
    <label className="inline-flex">
      <input type={type} name={name} checked={checked} onChange={onChange} className="peer sr-only" />
      <span className={chipVariants()}>{children}</span>
    </label>
  );
}

/**
 * Groups a set of ChipOptions under an accessible name. The visible
 * question text stays wherever the caller already renders it (unchanged
 * copy); `legend` is screen-reader-only and exists purely so the group of
 * radios/checkboxes has a programmatic name distinct from that visible text.
 */
export function ChipGroup({ legend, children }: { legend: string; children: ReactNode }) {
  return (
    <fieldset className="flex flex-col gap-1.5 border-0 p-0 m-0">
      <legend className="sr-only">{legend}</legend>
      <div className="flex flex-wrap gap-2">{children}</div>
    </fieldset>
  );
}
