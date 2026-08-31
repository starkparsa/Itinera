"use client";

import { useState } from "react";
import type { ConversationSummary, MessageOut, TripResponse } from "@/lib/types";
import { deleteConversation, generateTrip, getConversation, listConversations } from "@/lib/backend";
import Sidebar from "./Sidebar";
import ChatMessage from "./ChatMessage";
import ChatInput from "./ChatInput";
import CalendarPushButton from "./CalendarPushButton";
import { Alert, AlertDescription } from "@/components/ui/alert";

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
}: {
  initialConversations: ConversationSummary[];
  userEmail: string | null;
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

  async function refreshConversationList() {
    setConversations(await listConversations());
  }

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
      className="flex min-h-screen flex-col md:flex-row"
      data-tour-guide-mode={tourGuideMode ? "true" : undefined}
    >
      <Sidebar
        conversations={conversations}
        activeConversationId={activeConversationId}
        onSelect={loadConversation}
        onNewChat={startNewChat}
        onDelete={handleDelete}
        userEmail={userEmail}
      />

      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-4 py-6 md:px-8">
        <div className="flex items-center justify-between gap-4">
          <h1 className="flex items-center gap-2 text-xl font-semibold">
            <span aria-hidden>🧭</span> Itinera
          </h1>
          {topExportTrip && (
            <div className="flex shrink-0 items-center gap-2">
              <CalendarPushButton trip={topExportTrip} />
            </div>
          )}
        </div>

        {messages.length === 0 && !pendingPrompt && (
          <p className="my-4 text-muted-foreground">
            Describe a trip to start planning. Follow-ups in the same chat (e.g. &quot;make it a week instead&quot;)
            reference what you asked before.
          </p>
        )}

        <div className="my-4 flex flex-1 flex-col gap-4">
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

        {error && (
          <Alert variant="destructive" className="mb-2">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <ChatInput disabled={pendingPrompt !== null} onSubmit={handleSubmit} />
      </main>
    </div>
  );
}
