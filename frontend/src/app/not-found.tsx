import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";

// App-wide 404 -- replaces Next's unstyled default. Currently only reached
// via notFound() in /trips/[tripId]/page.tsx (a real 404 from getTrip(),
// not a network failure -- see backend.ts's GetTripResult), but this file
// covers any URL that doesn't match a route too.
export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-8 text-center">
      <img src="/logo-mark.png" alt="" aria-hidden className="h-12 w-12" />
      <h1 className="text-2xl font-semibold tracking-tight">Not found</h1>
      <p className="text-muted-foreground">That page — or trip — doesn&apos;t exist.</p>
      <Link href="/" className={buttonVariants({ size: "lg" })}>
        Back to Itinera
      </Link>
    </div>
  );
}
