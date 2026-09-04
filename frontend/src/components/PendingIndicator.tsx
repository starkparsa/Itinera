"use client";

import { useEffect, useState } from "react";

const STAGES = ["Reading your trip…", "Sketching the days…", "Checking the weather…", "Almost done…"];

// Purely cosmetic perceived-progress -- generateTrip() (lib/backend.ts) is a
// single non-streaming call, so the backend never tells the client which
// stage (classify -> generate -> weather) it's actually in. This cycles
// deliberately vague labels on a timer rather than claiming to know real
// backend state. Swap for real staged progress only if/when
// POST /trips/generate becomes a streaming endpoint -- that's a backend
// architecture change, not a frontend patch (see decisions.md).
export default function PendingIndicator() {
  const [stageIndex, setStageIndex] = useState(0);

  useEffect(() => {
    // Starts at 0 (useState's initializer) -- this component only ever
    // mounts fresh when a submit begins and unmounts when it ends, so
    // there's no stale state to reset here.
    const id = setInterval(() => {
      setStageIndex((i) => Math.min(i + 1, STAGES.length - 1));
    }, 4000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex justify-start">
      <div className="max-w-[80%] rounded-xl border bg-card px-4 py-3 text-sm text-muted-foreground italic">
        {STAGES[stageIndex]}
      </div>
    </div>
  );
}
