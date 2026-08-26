"use client";

import { useState } from "react";
import type { ConversationSummary, MessageOut, TripResponse } from "@/lib/types";
import { deleteConversation, generateTrip, getConversation, listConversations } from "@/lib/backend";
import Sidebar from "./Sidebar";
import ChatMessage from "./ChatMessage";
import ChatInput from "./ChatInput";
import CalendarPushButton from "./CalendarPushButton";

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
  }

  function startNewChat() {
    setActiveConversationId(null);
    setMessages([]);
    setError(null);
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
    <div className="app-layout">
      <Sidebar
        conversations={conversations}
        activeConversationId={activeConversationId}
        onSelect={loadConversation}
        onNewChat={startNewChat}
        onDelete={handleDelete}
        userEmail={userEmail}
      />

      <main className="main-panel">
        <div className="main-panel__header">
          <h1>🧭 AI Travel Planner</h1>
          {topExportTrip && (
            <div className="main-panel__header-actions">
              <CalendarPushButton trip={topExportTrip} />
            </div>
          )}
        </div>

        {messages.length === 0 && !pendingPrompt && (
          <p className="empty-hint">
            Describe a trip to start planning. Follow-ups in the same chat (e.g. &quot;make it a week instead&quot;) reference
            what you asked before.
          </p>
        )}

        <div className="message-list">
          {messages.map((msg) => (
            <ChatMessage key={msg.id} message={msg} />
          ))}
          {pendingPrompt && (
            <>
              <ChatMessage
                message={{ id: -1, role: "user", content: pendingPrompt, trip: null, created_at: "" }}
              />
              <div className="chat-message chat-message--assistant">
                <div className="chat-message__bubble chat-message__bubble--thinking">
                  Thinking — planning a full trip can take a few minutes, quick questions are much faster...
                </div>
              </div>
            </>
          )}
        </div>

        {error && <div className="banner banner--error">{error}</div>}

        <ChatInput disabled={pendingPrompt !== null} onSubmit={handleSubmit} />
      </main>
    </div>
  );
}
