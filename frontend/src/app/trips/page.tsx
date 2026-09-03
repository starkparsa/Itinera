import Link from "next/link";
import { redirect } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { auth } from "@/auth";
import { listTrips } from "@/lib/backend";
import TripCard from "@/components/TripCard";

export default async function TripsPage() {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }

  const trips = await listTrips();

  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col px-4 py-6 md:px-8">
      <div className="flex items-center justify-between gap-4">
        <div>
          <Link href="/" className="mb-1 flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
            <ArrowLeft className="size-3.5" /> Back to chat
          </Link>
          <h1 className="text-xl font-semibold">Your trips</h1>
          <p className="text-sm text-muted-foreground">
            {trips.length} {trips.length === 1 ? "trip" : "trips"} — every trip you&apos;ve planned or asked about.
          </p>
        </div>
      </div>

      {trips.length === 0 ? (
        <p className="my-8 text-muted-foreground">
          No trips yet — describe one in chat to get started.
        </p>
      ) : (
        <div className="my-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {trips.map((trip) => (
            <TripCard key={trip.id} trip={trip} />
          ))}
        </div>
      )}
    </main>
  );
}
