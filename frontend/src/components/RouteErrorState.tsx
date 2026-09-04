import Link from "next/link";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";

// Shared presentational error state for server-component routes (/trips,
// /trips/[tripId]) that got back a real "can't reach the backend" failure,
// not just "no data yet." No client JS needed for retry -- it's a plain
// link back to the same route, which re-runs the server component's fetch
// on navigation.
export default function RouteErrorState({ message, retryHref }: { message: string; retryHref: string }) {
  return (
    <Alert variant="destructive" className="my-6">
      <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
        <span>{message}</span>
        <Link href={retryHref} className={buttonVariants({ variant: "outline", size: "sm" })}>
          Try again
        </Link>
      </AlertDescription>
    </Alert>
  );
}
