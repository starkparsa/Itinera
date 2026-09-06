import { useRef, useState } from "react";
import { generateTrip, getConversation } from "@/lib/backend";
import type { ConversationDetail, MessageOut } from "@/lib/types";

// Extracted from ChatShell.tsx (2026-09 maintainability review). Owns
// conversation loading/caching *and* the pending/error state machine
// together -- evaluated splitting these into two hooks and rejected:
// loadConversation writes pending/error directly and applyConversationDetail
// clears error, so a clean split would require passing setters
// bidirectionally between two hooks for no real benefit.

// Covers both request shapes this hook makes -- sending a prompt
// (generateTrip) and loading a conversation (getConversation, from either a
// sidebar click or the OpenConversation bridge's initial-mount call).
// "submitting" carries the prompt so the pending bubble can echo it back;
// "loading" has nothing to echo, so it renders skeleton bubbles instead.
export type PendingState = { kind: "idle" } | { kind: "submitting"; prompt: string } | { kind: "loading" };

// A retryable error -- `retry` is whatever action produced the error,
// closed over its original arguments, so the "Try again" button never has
// to re-derive which of the two request shapes above failed.
export type ErrorState = { message: string; retry: () => void } | null;

// In-memory cache of already-fetched conversations, keyed by id -- module
// scope, not hook state, so it survives ChatShell remounting (e.g.
// navigating away to "/trips", outside the shared layout, and back).
// Revisiting a chat previously opened this session renders instantly from
// here instead of a network round trip. Written to on every successful
// fetch; never read across a real page reload.
const conversationCache = new Map<number, ConversationDetail>();

export function useConversationLoader() {
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [pending, setPending] = useState<PendingState>({ kind: "idle" });
  const [error, setError] = useState<ErrorState>(null);
  // Drives the [data-tour-guide-mode] accent override in globals.css --
  // set from whatever the backend last reported for this conversation, so
  // it reverts automatically the moment a load reflects the mode turning
  // back off (e.g. after an edit/new-trip turn, or switching chats).
  const [tourGuideMode, setTourGuideMode] = useState(false);

  // Monotonically increasing per loadConversation() call -- lets a call
  // tell whether it's still the most recent one by the time its async work
  // resolves. Needed because React Strict Mode's dev-only double-invoke of
  // effects (mount -> simulate-unmount -> mount again) fires the mount
  // effect that calls loadConversation twice in a row; without this, both
  // calls' results could apply, in either order, producing an inconsistent
  // final state. Also naturally covers the general case of the user
  // switching chats again before an earlier load finishes.
  const loadGenerationRef = useRef(0);

  function applyConversationDetail(id: number, detail: ConversationDetail) {
    setError(null);
    setActiveConversationId(id);
    setMessages(detail.messages);
    setTourGuideMode(detail.tour_guide_mode);
  }

  // showLoading=false is used only for the immediate post-generate load in
  // submitPrompt below -- that call already has its own "submitting" bubble
  // on screen, so touching `pending` here would just flash it to a skeleton
  // and back for no reason. Every other caller (sidebar click, the
  // OpenConversation mount effect) leaves it true and gets the real
  // loading state.
  //
  // A conversation already fetched this session (conversationCache above)
  // renders immediately from that cached copy -- no loading skeleton, no
  // network wait -- and then quietly re-fetches in the background to catch
  // anything that changed (e.g. a refreshed weather forecast) without
  // flashing a loading state for content already on screen.
  //
  // skipCache=true is for submitPrompt's post-send reload: generateTrip
  // just changed this exact conversation server-side (a new message was
  // added), so the cached copy is now known-stale -- rendering it first
  // would flash the just-sent message away for a moment until the
  // background revalidation above caught up.
  async function loadConversation(id: number, opts: { showLoading?: boolean; skipCache?: boolean } = {}) {
    const { showLoading = true, skipCache = false } = opts;
    const myGeneration = ++loadGenerationRef.current;
    const cached = skipCache ? undefined : conversationCache.get(id);

    if (cached) {
      applyConversationDetail(id, cached);
      // Background revalidation -- deliberately not awaited, no pending
      // state touched, and no error surfaced on failure: the cached
      // content already on screen is a perfectly good result on its own,
      // this is purely a "keep it fresh" best effort.
      getConversation(id)
        .then((fresh) => {
          if (!fresh) return;
          conversationCache.set(id, fresh);
          // Only apply if no newer loadConversation call (a re-invoke from
          // Strict Mode, or the user switching chats again) has started
          // since this one began.
          if (loadGenerationRef.current === myGeneration) applyConversationDetail(id, fresh);
        })
        .catch(() => {
          // Stale cached content stays on screen; nothing to surface here.
        });
      return;
    }

    if (showLoading) setPending({ kind: "loading" });
    try {
      const detail = await getConversation(id);
      if (loadGenerationRef.current !== myGeneration) return; // superseded -- discard
      if (!detail) {
        setError({ message: "Couldn't load that chat.", retry: () => loadConversation(id, opts) });
        return;
      }
      conversationCache.set(id, detail);
      applyConversationDetail(id, detail);
    } finally {
      if (showLoading && loadGenerationRef.current === myGeneration) setPending({ kind: "idle" });
    }
  }

  function startNewChat() {
    setActiveConversationId(null);
    setMessages([]);
    setError(null);
    setTourGuideMode(false);
  }

  // Exposed via ChatShellContext -- the one entry point a page (through the
  // OpenConversation bridge) uses to say "this is the conversation I want
  // shown." null means the fresh "New chat" state.
  function openConversation(id: number | null) {
    if (id == null) {
      startNewChat();
    } else {
      loadConversation(id);
    }
  }

  // Applies a server-fetched conversation detail with zero client-side
  // network call -- see ChatShellContextValue's comment (ChatShell.tsx)
  // for why this exists. Still bumps loadGenerationRef so a concurrent/
  // later loadConversation call (e.g. the user clicking a different chat
  // before this one even finishes mounting) correctly supersedes it.
  function seedConversation(id: number, detail: ConversationDetail) {
    ++loadGenerationRef.current;
    conversationCache.set(id, detail);
    applyConversationDetail(id, detail);
  }

  function invalidateConversation(id: number) {
    conversationCache.delete(id);
  }

  // Absorbs ChatShell.tsx's old handleSubmit -- its body only touches
  // pending/error/loadConversation (all owned by this hook) plus a
  // callback out to refreshConversationList (owned by ChatShell itself,
  // concern (a)), passed in here rather than reaching across hooks.
  async function submitPrompt(prompt: string, afterNewConversation: () => Promise<void> | void) {
    setError(null);
    setPending({ kind: "submitting", prompt });
    try {
      const result = await generateTrip(prompt, activeConversationId);
      if (!result.ok || !result.data) {
        setError({
          message: result.error ?? "Couldn't reach the planner backend",
          retry: () => submitPrompt(prompt, afterNewConversation),
        });
        return;
      }
      const newConversationId = result.data.conversation_id;
      if (newConversationId) {
        await loadConversation(newConversationId, { showLoading: false, skipCache: true });
        await afterNewConversation();
      }
    } finally {
      setPending({ kind: "idle" });
    }
  }

  return {
    activeConversationId,
    messages,
    pending,
    error,
    tourGuideMode,
    loadConversation,
    startNewChat,
    openConversation,
    seedConversation,
    invalidateConversation,
    submitPrompt,
  };
}
