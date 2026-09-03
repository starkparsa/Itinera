"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Menu, Luggage } from "lucide-react";
import type { ConversationSummary, MessageOut, TripResponse } from "@/lib/types";
import { deleteConversation, generateTrip, getConversation, listConversations } from "@/lib/backend";
import Sidebar from "./Sidebar";
import ChatMessage from "./ChatMessage";
import ChatInput from "./ChatInput";
import CalendarPushButton from "./CalendarPushButton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";

// Newest message first whose trip has a resolved start_date -- port of
// streamlit_app.py::_latest_exportable_trip(). Export stays hidden entirely
// (not disabled) until this exists, per the explicit gating decision.
function latestExportableTrip(messages: MessageOut[]): TripResponse | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const trip = messages[i].trip;
    if (trip && trip.start_date && trip.trip_id) return trip;
  }
  return null;
}

export default function ChatApp({
  initialConversations,
  userEmail,
  initialConversationId,
  rightPanel,
}: {
  initialConversations: ConversationSummary[];
  userEmail: string | null;
  // Pre-selects a conversation on mount -- used by the Trip Hub page
  // (app/trips/[tripId]/page.tsx) to open straight into a specific trip's
  // chat instead of the empty "describe a trip" state. Omitted (the
  // default) on the plain "/" entry point, which is unaffected.
  initialConversationId?: number | null;
  // Extra column rendered as a sibling of <main>, after it -- the Trip Hub
  // page's collapsible Weather panel. Reusing this whole component rather
  // than re-deriving chat rendering avoids two sources of truth for the
  // same message list.
  rightPanel?: React.ReactNode;
}) {
  const [conversations, setConversations] = useState<ConversationSummary[]>(initialConversations);
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Drives the [data-tour-guide-mode] accent override in globals.css --
  // set from whatever the backend last reported for this conversation, so
  // it reverts automatically the moment a load reflects the mode turning
  // back off (e.g. after an edit/new-trip turn, or switching chats).
  const [tourGuideMode, setTourGuideMode] = useState(false);
  // Collapsed by default -- "nothing extra on screen until asked for it,"
  // per the Trip Hub v2 direction (decisions.md's UI styling entry).
  const [sidebarOpen, setSidebarOpen] = useState(false);

  async function refreshConversationList() {
    setConversations(await listConversations());
  }

  // Runs once on mount only (the Trip Hub page never changes which trip a
  // given mounted page points at -- navigating to a different trip is a
  // full route change, not a prop update on this same instance).
  useEffect(() => {
    if (initialConversationId) loadConversation(initialConversationId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadConversation(id: number) {
    const detail = await getConversation(id);
    if (!detail) {
      setError("Couldn't load that chat.");
      return;
    }
    setActiveConversationId(id);
    setMessages(detail.messages);
    setTourGuideMode(detail.tour_guide_mode);
  }

  function startNewChat() {
    setActiveConversationId(null);
    setMessages([]);
    setError(null);
    setTourGuideMode(false);
  }

  async function handleDelete(id: number) {
    await deleteConversation(id);
    if (activeConversationId === id) startNewChat();
    await refreshConversationList();
  }

  async function handleSubmit(prompt: string) {
    setError(null);
    setPendingPrompt(prompt);
    try {
      const result = await generateTrip(prompt, activeConversationId);
      if (!result.ok || !result.data) {
        setError(result.error ?? "Couldn't reach the planner backend");
        return;
      }
      const newConversationId = result.data.conversation_id;
      if (newConversationId) {
        await loadConversation(newConversationId);
        await refreshConversationList();
      }
    } finally {
      setPendingPrompt(null);
    }
  }

  // Initial conversation list comes from the server component (page.tsx) as
  // a prop -- no need for an effect to fetch it again on mount. It's
  // refreshed explicitly after any action that changes it (send, delete).
  const topExportTrip = latestExportableTrip(messages);

  return (
    <div
      className="flex h-dvh flex-col overflow-hidden md:flex-row"
      data-tour-guide-mode={tourGuideMode ? "true" : undefined}
    >
      {sidebarOpen && (
        <Sidebar
          conversations={conversations}
          activeConversationId={activeConversationId}
          onSelect={loadConversation}
          onNewChat={startNewChat}
          onDelete={handleDelete}
          userEmail={userEmail}
        />
      )}

      {/* h-dvh + overflow-hidden above (not min-h-screen) plus min-h-0 here
          is what actually makes the middle region scrollable instead of
          the whole page -- a flex child's default min-height is `auto`,
          which silently blocks it from ever shrinking/scrolling in a
          column flex layout without this.

          The centered max-w-3xl reading column only makes sense on the
          plain "/" chat, where <main> is the entire row. On the Trip Hub
          page (rightPanel set), that same fixed cap left <main> centered
          in whatever space was left over next to the panel instead of
          actually filling it -- so drop the cap there and let the chat
          block stretch to whatever width the row actually gives it. */}
      <main
        className={`flex min-h-0 flex-1 flex-col overflow-hidden px-4 md:px-8 ${
          rightPanel ? "w-full" : "mx-auto w-full max-w-3xl"
        }`}
      >
        {/* Locked to the top -- shrink-0 so the scrollable region below never pushes it out of view. */}
        <div className="flex shrink-0 items-center justify-between gap-4 pt-6 pb-2">
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="icon"
              className="size-8"
              aria-label={sidebarOpen ? "Hide chats" : "Show chats"}
              onClick={() => setSidebarOpen((open) => !open)}
            >
              <Menu className="size-4" />
            </Button>
            <h1 className="flex items-center gap-2 text-xl font-semibold">
              <img src="/logo-mark.png" alt="" aria-hidden className="h-5 w-5" /> Itinera
            </h1>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Link href="/trips" className={buttonVariants({ variant: "outline", size: "sm" })}>
              <Luggage className="size-4" />
              Your trips
            </Link>
            {topExportTrip && <CalendarPushButton trip={topExportTrip} />}
          </div>
        </div>

        {/* The only scrollable region -- everything above and below this stays put. */}
        <div className="min-h-0 flex-1 overflow-y-auto py-4">
          {messages.length === 0 && !pendingPrompt && (
            <p className="text-muted-foreground">
              Describe a trip to start planning. Follow-ups in the same chat (e.g. &quot;make it a week
              instead&quot;) reference what you asked before.
            </p>
          )}

          <div className="flex flex-col gap-4">
            {messages.map((msg) => (
              <ChatMessage key={msg.id} message={msg} />
            ))}
            {pendingPrompt && (
              <>
                <ChatMessage message={{ id: -1, role: "user", content: pendingPrompt, trip: null, created_at: "" }} />
                <div className="flex justify-start">
                  <div className="max-w-[80%] rounded-xl border bg-card px-4 py-3 text-sm text-muted-foreground italic">
                    Thinking — planning a full trip can take a few minutes, quick questions are much faster...
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        {/* Locked to the bottom -- shrink-0 for the same reason the header is. */}
        <div className="shrink-0 pt-2 pb-6">
          {error && (
            <Alert variant="destructive" className="mb-2">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <ChatInput disabled={pendingPrompt !== null} onSubmit={handleSubmit} />
        </div>
      </main>

      {rightPanel}
    </div>
  );
}
