import { notFound, redirect } from "next/navigation";
import { auth } from "@/auth";
import { getTrip, listConversations } from "@/lib/backend";
import ChatApp from "@/components/ChatApp";
import TripHubPanel from "@/components/TripHubPanel";

export default async function TripHubPage({ params }: { params: Promise<{ tripId: string }> }) {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }

  const { tripId } = await params;
  const trip = await getTrip(Number(tripId));
  if (!trip) {
    notFound();
  }

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
