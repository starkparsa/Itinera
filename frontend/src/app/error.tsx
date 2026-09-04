"use client";

import { useEffect } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

// App Router error boundary -- catches anything thrown by a page or layout
// under app/ (excluding layout.tsx itself, which would need global-error.tsx)
// that isn't already handled inline, e.g. by the ok/error results
// listTrips()/getTrip() now return. Must be a Client Component per Next's
// convention; `reset()` re-renders the segment rather than a full reload.
export default function ErrorBoundary({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-8 text-center">
      <Alert variant="destructive" className="max-w-sm text-left">
        <AlertDescription>Something went wrong loading this page. Try again, or come back in a moment.</AlertDescription>
      </Alert>
      <Button onClick={() => reset()}>Try again</Button>
    </div>
  );
}
