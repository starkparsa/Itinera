import { useLayoutEffect, useRef } from "react";
import type { MessageOut } from "@/lib/types";

// Extracted from ChatShell.tsx (2026-09 maintainability review).

// In-memory scroll-position cache, keyed by conversation id -- module scope,
// not hook state. Originally built to survive ChatApp remounting on every
// route change between "/" and "/trips/[tripId]"; now that ChatShell lives
// in a shared layout and doesn't remount for that anymore, this is a
// smaller but still real optimization: scroll position for a chat you've
// viewed earlier this session survives navigating away to "/trips"
// (outside the shared layout) and back. Module scope (not useState/useRef
// inside the hook) is what makes it survive a remount at all -- ES module
// scope is a singleton, shared across every mount of this hook.
const scrollPositionCache = new Map<number, number>();

// Restores scroll position on the message log whenever it has something
// new to show -- previously this was never touched, so switching chats
// (or reopening one after navigating away) left the log wherever it
// happened to be, usually scrolled to the top of a long conversation
// instead of the latest message.
//
// Switching to a different conversation: restore its remembered scroll
// position (scrollPositionCache above, see handleMessageLogScroll below)
// if it has one -- i.e. "where the user left it" -- otherwise this is the
// first time it's been opened this session, so jump straight to the
// latest message. Staying on the same conversation (a message was just
// sent or a reply arrived): always jump to the bottom, regardless of any
// remembered position -- a fresh message is exactly what a mid-scroll
// remembered position would otherwise hide.
export function useScrollRestore(
  activeConversationId: number | null,
  messages: MessageOut[],
  pendingKind: string,
) {
  const messageLogRef = useRef<HTMLDivElement>(null);
  // Tracks which conversation the log was last scrolled for, so the effect
  // can tell "just switched to a different chat" (restore where the user
  // left it, or jump to the bottom if that's the first visit) apart from
  // "same chat, a message was just sent/received" (always jump to the
  // bottom for that one, regardless of any remembered position).
  const scrolledForConversationRef = useRef<number | null>(null);

  // A layout effect (not a plain effect) so this runs before the browser
  // paints the new content -- otherwise the wrong position would flash on
  // screen for a frame first.
  useLayoutEffect(() => {
    const el = messageLogRef.current;
    if (!el || pendingKind === "loading") return;

    const switchedConversation = scrolledForConversationRef.current !== activeConversationId;
    scrolledForConversationRef.current = activeConversationId;

    if (switchedConversation && activeConversationId != null) {
      const stored = scrollPositionCache.get(activeConversationId);
      el.scrollTop = stored ?? el.scrollHeight;
    } else {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages, activeConversationId, pendingKind]);

  function handleMessageLogScroll(e: React.UIEvent<HTMLDivElement>) {
    if (activeConversationId != null) {
      scrollPositionCache.set(activeConversationId, e.currentTarget.scrollTop);
    }
  }

  function invalidateScrollPosition(id: number) {
    scrollPositionCache.delete(id);
  }

  return { messageLogRef, handleMessageLogScroll, invalidateScrollPosition };
}
