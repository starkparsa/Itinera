import { getConversation } from "@/lib/backend";
import OpenConversation from "@/components/OpenConversation";

// Auth + the conversation list are now handled once by app/(chat)/layout.tsx,
// shared with "/trips/[tripId]" -- this page only needs to resolve which
// conversation (if any) should be open here and hand that off to the
// persistent ChatShell via the OpenConversation bridge.
export default async function Home({ searchParams }: { searchParams: Promise<{ chat?: string }> }) {
  // ?chat=<id> is how the sidebar (ChatShell's handleSelectConversation)
  // reflects "which chat is open" in the URL on this route -- Trip Hub
  // pages use a real /trips/[tripId] segment instead, but a plain
  // conversation may not have a generated Trip row yet, so it has no such
  // URL to go to; this query param works for every conversation uniformly.
  const { chat } = await searchParams;
  const parsedId = chat ? Number(chat) : null;
  const initialConversationId = Number.isFinite(parsedId) ? parsedId : null;

  // Fetched server-side, same reasoning as trips/[tripId]/page.tsx: avoids
  // OpenConversation's client-side mount effect having to fetch this
  // itself, which was a second slow round trip stacked after the page's
  // own navigation on a fresh mount of this route (e.g. navigating here
  // from a Trip Hub page via a conversation with no Trip row yet).
  const conversationDetail = initialConversationId ? await getConversation(initialConversationId) : null;

  return <OpenConversation id={initialConversationId} initialDetail={conversationDetail} />;
}
