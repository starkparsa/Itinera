import { notFound } from "next/navigation";
import { getConversation, getTrip } from "@/lib/backend";
import OpenConversation from "@/components/OpenConversation";
import TripHubPanel from "@/components/TripHubPanel";
import RouteErrorState from "@/components/RouteErrorState";

// Auth + the conversation list are now handled once by app/(chat)/layout.tsx
// (shared with "/") -- this page only fetches what's specific to this one
// trip, then hands the conversation id off to the persistent ChatShell via
// the OpenConversation bridge and renders TripHubPanel into the shell's
// right-panel slot (ChatShell.tsx renders {children} there).
export default async function TripHubPage({ params }: { params: Promise<{ tripId: string }> }) {
  const { tripId } = await params;
  const result = await getTrip(Number(tripId));
  // notFound() is reserved for a real 404 from the backend -- any other
  // failure (network error, 5xx) falls through to the inline error state
  // below instead, so a transient outage isn't told to the user as "this
  // trip doesn't exist."
  if (result.notFound) {
    notFound();
  }
  if (!result.ok || !result.data) {
    // Not <main id="main-content"> -- ChatShell (app/(chat)/layout.tsx)
    // always renders its own <main id="main-content"> now regardless of
    // what this page returns, since the shell is persistent rather than
    // conditionally skipped the way the old per-page ChatApp was. A second
    // element with the same id here would be a duplicate landmark and
    // break the skip-link's target. This renders into the shell's
    // right-panel slot instead, alongside (not replacing) the shell's own
    // chat UI.
    return (
      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col px-4 py-6 md:px-8">
        <RouteErrorState message={result.error ?? "Couldn't load this trip."} retryHref={`/trips/${tripId}`} />
      </div>
    );
  }
  const trip = result.data;

  // Fetched here, server-side, alongside getTrip() above -- rather than
  // leaving it to OpenConversation's client-side mount effect to fetch
  // afterward. getConversation() is a Server Action ("use server" in
  // backend.ts): calling it directly from this Server Component runs it
  // in the same request, with no extra browser round trip, unlike a
  // client component calling it (which does cross the network). Without
  // this, a Trip Hub visit did getTrip() here, sent the page down, then
  // waited for the client to mount and *separately* fetch the
  // conversation -- two slow sequential round trips per navigation
  // instead of one, which is what made switching chats feel like it was
  // "double loading" even outside of anything Strict-Mode-related.
  const conversationDetail = trip.conversation_id ? await getConversation(trip.conversation_id) : null;

  // The day-by-day itinerary isn't re-rendered separately here -- it
  // already appears via the existing TripView component inside the chat
  // message that generated it (ChatShell -> ChatMessage -> TripView).
  // Building a second, parallel itinerary renderer for this page would
  // give the same data two sources of truth for no real benefit.
  return (
    <>
      <OpenConversation id={trip.conversation_id} initialDetail={conversationDetail} />
      <TripHubPanel trip={trip} />
    </>
  );
}
