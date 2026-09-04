import { notFound, redirect } from "next/navigation";
import { auth } from "@/auth";
import { getTrip, listConversations } from "@/lib/backend";
import ChatApp from "@/components/ChatApp";
import TripHubPanel from "@/components/TripHubPanel";
import RouteErrorState from "@/components/RouteErrorState";

export default async function TripHubPage({ params }: { params: Promise<{ tripId: string }> }) {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }

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
    return (
      <main id="main-content" className="mx-auto flex w-full max-w-2xl flex-1 flex-col px-4 py-6 md:px-8">
        <RouteErrorState message={result.error ?? "Couldn't load this trip."} retryHref={`/trips/${tripId}`} />
      </main>
    );
  }
  const trip = result.data;

  const conversations = await listConversations();

  // The day-by-day itinerary isn't re-rendered separately here -- it
  // already appears via the existing TripView component inside the chat
  // message that generated it (ChatApp -> ChatMessage -> TripView).
  // Building a second, parallel itinerary renderer for this page would
  // give the same data two sources of truth for no real benefit.
  return (
    <ChatApp
      initialConversations={conversations}
      userEmail={session.user.email ?? null}
      initialConversationId={trip.conversation_id}
      rightPanel={<TripHubPanel trip={trip} />}
    />
  );
}
