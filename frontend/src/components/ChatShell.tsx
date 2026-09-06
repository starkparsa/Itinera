"use client";

import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Menu, Luggage } from "lucide-react";
import type { ConversationDetail, ConversationSummary, MessageOut, TripResponse } from "@/lib/types";
import { deleteConversation, generateTrip, getConversation, listConversations } from "@/lib/backend";
import Sidebar from "./Sidebar";
import ChatMessage from "./ChatMessage";
import ChatInput from "./ChatInput";
import CalendarPushButton from "./CalendarPushButton";
import PendingIndicator from "./PendingIndicator";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useIsMobile } from "@/hooks/use-mobile";

// In-memory scroll-position cache, keyed by conversation id -- module scope,
// not component state. Originally built to survive ChatApp remounting on
// every route change between "/" and "/trips/[tripId]"; now that ChatShell
// itself lives in a shared layout and doesn't remount for that anymore,
// this is a smaller but still real optimization: scroll position for a
// chat you've viewed earlier this session survives navigating away to
// "/trips" (outside the shared layout) and back.
const scrollPositionCache = new Map<number, number>();

// In-memory cache of already-fetched conversations, keyed by id -- same
// module-scope lifetime/reasoning as scrollPositionCache above. Revisiting
// a chat previously opened this session renders instantly from here
// instead of a network round trip. Written to on every successful fetch;
// never read across a real page reload.
const conversationCache = new Map<number, ConversationDetail>();

// What a page (via the OpenConversation bridge, components/OpenConversation.tsx)
// needs to tell the shell which conversation to show.
interface ChatShellContextValue {
  activeConversationId: number | null;
  // id === null starts a fresh, empty chat (the "New chat" state).
  openConversation: (id: number | null) => void;
  // Like openConversation, but for when the page has *already* fetched the
  // conversation's detail server-side (see OpenConversation's initialDetail
  // prop) -- applies it directly with zero client-side network call. Used
  // instead of openConversation whenever the caller already has the data,
  // so a Trip Hub / "?chat=" page load does one combined server round trip
  // (getTrip + getConversation, or just getConversation) instead of a
  // server fetch followed by a *second*, separate client-initiated one
  // after the page has already mounted -- previously visible in the
  // Network tab as two sequential slow requests per navigation and felt
  // like the chat "double loading."
  seedConversation: (id: number, detail: ConversationDetail) => void;
}

const ChatShellContext = createContext<ChatShellContextValue | null>(null);

export function useChatShellContext(): ChatShellContextValue {
  const ctx = useContext(ChatShellContext);
  if (!ctx) {
    throw new Error("useChatShellContext must be used within <ChatShell>");
  }
  return ctx;
}

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

// Covers both request shapes this component makes -- sending a prompt
// (generateTrip) and loading a conversation (getConversation, from either a
// sidebar click or the OpenConversation bridge's initial-mount call).
// "submitting" carries the prompt so the pending bubble can echo it back;
// "loading" has nothing to echo, so it renders skeleton bubbles instead.
type PendingState = { kind: "idle" } | { kind: "submitting"; prompt: string } | { kind: "loading" };

// A retryable error -- `retry` is whatever action produced the error,
// closed over its original arguments, so the "Try again" button never has
// to re-derive which of the two request shapes above failed.
type ErrorState = { message: string; retry: () => void } | null;

function ConversationSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-hidden>
      <div className="flex justify-end">
        <Skeleton className="h-10 w-2/5 rounded-xl" />
      </div>
      <div className="flex justify-start">
        <Skeleton className="h-24 w-3/5 rounded-xl" />
      </div>
    </div>
  );
}

export default function ChatShell({
  initialConversations,
  userEmail,
  children,
}: {
  initialConversations: ConversationSummary[];
  userEmail: string | null;
  // Rendered as a sibling of <main>, after it -- the Trip Hub page's
  // OpenConversation bridge (invisible) plus, only there, its collapsible
  // Weather/Saved Places panel. Reusing this whole shell for both routes
  // rather than duplicating chat rendering avoids two sources of truth for
  // the same message list.
  children?: React.ReactNode;
}) {
  const [conversations, setConversations] = useState<ConversationSummary[]>(initialConversations);
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [pending, setPending] = useState<PendingState>({ kind: "idle" });
  const [error, setError] = useState<ErrorState>(null);
  // Drives the [data-tour-guide-mode] accent override in globals.css --
  // set from whatever the backend last reported for this conversation, so
  // it reverts automatically the moment a load reflects the mode turning
  // back off (e.g. after an edit/new-trip turn, or switching chats).
  const [tourGuideMode, setTourGuideMode] = useState(false);
  // Collapsed by default -- "nothing extra on screen until asked for it,"
  // per the Trip Hub v2 direction (decisions.md's UI styling entry). Same
  // boolean drives both presentations below (inline column on desktop, an
  // overlay Sheet on mobile) -- there's one open/closed concept, just two
  // ways of rendering it depending on viewport.
  //
  // Persisted to localStorage as a secondary safety net (e.g. a hard
  // refresh) -- now that this shell lives in a shared layout instead of
  // being remounted per page, the toggle already survives normal
  // navigation between "/" and "/trips/[tripId]" on its own.
  //
  // Initial render always starts closed (matching the server-rendered HTML)
  // and an effect flips it open right after mount if storage says so --
  // reading localStorage in the initializer instead would make the client's
  // first render disagree with the server's, which React flags as a
  // hydration mismatch.
  const [sidebarOpen, setSidebarOpenState] = useState(false);

  useEffect(() => {
    try {
      if (window.localStorage.getItem("itinera:sidebar-open") === "true") {
        setSidebarOpenState(true);
      }
    } catch {
      // Private browsing / storage disabled -- just stays closed.
    }
  }, []);

  function setSidebarOpen(next: boolean | ((prev: boolean) => boolean)) {
    setSidebarOpenState((prev) => {
      const value = typeof next === "function" ? next(prev) : next;
      try {
        window.localStorage.setItem("itinera:sidebar-open", String(value));
      } catch {
        // Private browsing / storage disabled -- the toggle still works
        // for this instance, it just won't survive navigation.
      }
      return value;
    });
  }
  // Real breakpoint check (not just a CSS class) -- deciding which of the
  // two presentations to *mount* has to happen in JS. A CSS-only "hide the
  // Sheet at md:" would still leave Base UI's Dialog open and trapping
  // focus/scroll-locking the page behind an invisible overlay on desktop.
  const isMobile = useIsMobile();
  const router = useRouter();
  const pathname = usePathname();

  // Scroll position handling for the message log -- see the layout effect
  // below for the actual restore/jump-to-bottom logic.
  const messageLogRef = useRef<HTMLDivElement>(null);
  // Tracks which conversation the log was last scrolled for, so the effect
  // can tell "just switched to a different chat" (restore where the user
  // left it, or jump to the bottom if that's the first visit) apart from
  // "same chat, a message was just sent/received" (always jump to the
  // bottom for that one, regardless of any remembered position).
  const scrolledForConversationRef = useRef<number | null>(null);

  // Monotonically increasing per loadConversation() call -- lets a call
  // tell whether it's still the most recent one by the time its async work
  // resolves. Needed because React Strict Mode's dev-only double-invoke of
  // effects (mount -> simulate-unmount -> mount again) fires the mount
  // effect that calls loadConversation twice in a row; without this, both
  // calls' results could apply, in either order, producing an inconsistent
  // final state. Also naturally covers the general case of the user
  // switching chats again before an earlier load finishes.
  const loadGenerationRef = useRef(0);

  async function refreshConversationList() {
    setConversations(await listConversations());
  }

  function applyConversationDetail(id: number, detail: ConversationDetail) {
    setError(null);
    setActiveConversationId(id);
    setMessages(detail.messages);
    setTourGuideMode(detail.tour_guide_mode);
  }

  // showLoading=false is used only for the immediate post-generate load in
  // handleSubmit below -- that call already has its own "submitting" bubble
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
  // skipCache=true is for handleSubmit's post-send reload: generateTrip
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

  // Restores scroll position on the message log whenever it has something
  // new to show -- previously this was never touched, so switching chats
  // (or reopening one after navigating away) left the log wherever it
  // happened to be, usually scrolled to the top of a long conversation
  // instead of the latest message. A layout effect (not a plain effect) so
  // this runs before the browser paints the new content -- otherwise the
  // wrong position would flash on screen for a frame first.
  //
  // Switching to a different conversation: restore its remembered scroll
  // position (scrollPositionCache above, see the log's onScroll below) if
  // it has one -- i.e. "where the user left it" -- otherwise this is the
  // first time it's been opened this session, so jump straight to the
  // latest message. Staying on the same conversation (a message was just
  // sent or a reply arrived): always jump to the bottom, regardless of any
  // remembered position -- a fresh message is exactly what a mid-scroll
  // remembered position would otherwise hide.
  useLayoutEffect(() => {
    const el = messageLogRef.current;
    if (!el || pending.kind === "loading") return;

    const switchedConversation = scrolledForConversationRef.current !== activeConversationId;
    scrolledForConversationRef.current = activeConversationId;

    if (switchedConversation && activeConversationId != null) {
      const stored = scrollPositionCache.get(activeConversationId);
      el.scrollTop = stored ?? el.scrollHeight;
    } else {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages, activeConversationId, pending.kind]);

  function handleMessageLogScroll(e: React.UIEvent<HTMLDivElement>) {
    if (activeConversationId != null) {
      scrollPositionCache.set(activeConversationId, e.currentTarget.scrollTop);
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
  // network call -- see ChatShellContextValue's comment above for why this
  // exists. Still bumps loadGenerationRef so a concurrent/later
  // loadConversation call (e.g. the user clicking a different chat before
  // this one even finishes mounting) correctly supersedes it.
  function seedConversation(id: number, detail: ConversationDetail) {
    ++loadGenerationRef.current;
    conversationCache.set(id, detail);
    applyConversationDetail(id, detail);
  }

  async function handleDelete(id: number) {
    await deleteConversation(id);
    conversationCache.delete(id);
    scrollPositionCache.delete(id);
    if (activeConversationId === id) startNewChat();
    await refreshConversationList();
  }

  // Selecting a chat or starting a new one closes the mobile Sheet overlay
  // (it's covering the screen, so leaving it up would hide the result of
  // the very action just taken) but leaves the desktop inline column open
  // -- there it's just occupying a column next to the chat, not blocking it.
  //
  // Also reflects the selection in the URL -- previously this only updated
  // in-memory state, so the address bar stayed wherever it already was no
  // matter which chat was open, and refresh/back/sharing a link all
  // silently lost the selection.
  //
  // A conversation that has generated an itinerary always routes to its
  // own "/trips/[tripId]" Trip Hub page -- picking it from the sidebar used
  // to always land on the plain chat view instead, which meant Trip Hub
  // (and its Weather/Saved Places panel) was only reachable via Your Trips,
  // not from the sidebar you're actually using to jump between chats. Only
  // a conversation with no Trip row yet (nothing generated so far) falls
  // back to "/?chat=<id>", since it has no Trip Hub page to go to.
  async function handleSelectConversation(id: number) {
    const tripId = conversations.find((c) => c.id === id)?.trip_id;
    if (tripId) {
      router.push(`/trips/${tripId}`);
    } else if (pathname === "/") {
      // Same route already -- load inline instead of only navigating, so
      // this doesn't wait on a server round-trip for something already
      // fetchable client-side.
      await loadConversation(id);
      router.push(`/?chat=${id}`, { scroll: false });
    } else {
      router.push(`/?chat=${id}`);
    }
    if (isMobile) setSidebarOpen(false);
  }

  function handleNewChat() {
    if (pathname === "/") {
      startNewChat();
      router.push("/", { scroll: false });
    } else {
      router.push("/");
    }
    if (isMobile) setSidebarOpen(false);
  }

  async function handleSubmit(prompt: string) {
    setError(null);
    setPending({ kind: "submitting", prompt });
    try {
      const result = await generateTrip(prompt, activeConversationId);
      if (!result.ok || !result.data) {
        setError({
          message: result.error ?? "Couldn't reach the planner backend",
          retry: () => handleSubmit(prompt),
        });
        return;
      }
      const newConversationId = result.data.conversation_id;
      if (newConversationId) {
        await loadConversation(newConversationId, { showLoading: false, skipCache: true });
        await refreshConversationList();
      }
    } finally {
      setPending({ kind: "idle" });
    }
  }

  // Initial conversation list comes from the server component (layout.tsx)
  // as a prop -- no need for an effect to fetch it again on mount. It's
  // refreshed explicitly after any action that changes it (send, delete).
  const topExportTrip = latestExportableTrip(messages);

  return (
    <ChatShellContext.Provider value={{ activeConversationId, openConversation, seedConversation }}>
      <div
        className="flex h-dvh flex-col overflow-hidden md:flex-row"
        data-tour-guide-mode={tourGuideMode ? "true" : undefined}
      >
        {/* Same "collapsed by default, opened only on request" chrome either
            way -- desktop renders it inline (pushes/shares the row, per the
            Trip Hub v2 decision), mobile renders it as a full-height overlay
            Sheet instead of pushing the compose box off-screen below a
            stacked, full-width sidebar block. */}
        {isMobile ? (
          <Sheet open={sidebarOpen} onOpenChange={setSidebarOpen}>
            <SheetContent side="left" className="w-4/5 gap-0 p-0 sm:max-w-xs">
              <SheetTitle className="sr-only">Chats</SheetTitle>
              <Sidebar
                conversations={conversations}
                activeConversationId={activeConversationId}
                onSelect={handleSelectConversation}
                onNewChat={handleNewChat}
                onDelete={handleDelete}
                userEmail={userEmail}
              />
            </SheetContent>
          </Sheet>
        ) : (
          sidebarOpen && (
            <Sidebar
              conversations={conversations}
              activeConversationId={activeConversationId}
              onSelect={handleSelectConversation}
              onNewChat={handleNewChat}
              onDelete={handleDelete}
              userEmail={userEmail}
            />
          )
        )}

        {/* h-dvh + overflow-hidden above (not min-h-screen) plus min-h-0 here
            is what actually makes the middle region scrollable instead of
            the whole page -- a flex child's default min-height is `auto`,
            which silently blocks it from ever shrinking/scrolling in a
            column flex layout without this. Always full-width, on both "/"
            and the Trip Hub page. */}
        <main
          id="main-content"
          className="flex min-h-0 w-full flex-1 flex-col overflow-hidden px-4 md:px-8"
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
              {tourGuideMode && (
                <Badge variant="secondary" className="border-primary/30 text-primary">
                  🧭 Tour guide mode
                </Badge>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Link href="/trips" className={buttonVariants({ variant: "outline", size: "sm" })}>
                <Luggage className="size-4" />
                Your trips
              </Link>
              {topExportTrip && <CalendarPushButton trip={topExportTrip} />}
            </div>
          </div>

          {/* The only scrollable region -- everything above and below this stays put.
              aria-live="polite" announces each new message as it arrives (assistant
              replies, in particular) without stealing focus -- role="log" tells
              screen readers this is a running transcript, not a single alert. */}
          <div
            ref={messageLogRef}
            onScroll={handleMessageLogScroll}
            className="min-h-0 flex-1 overflow-y-auto py-4"
            role="log"
            aria-live="polite"
          >
            {pending.kind === "loading" ? (
              <>
                {/* ConversationSkeleton itself is aria-hidden (it's decorative) --
                    without this, a screen reader user switching chats would get
                    total silence from the role="log" region until real content
                    arrives, instead of the visual skeleton sighted users see. */}
                <span className="sr-only" role="status">
                  Loading conversation…
                </span>
                <ConversationSkeleton />
              </>
            ) : (
              <>
                {messages.length === 0 && pending.kind === "idle" && (
                  <p className="text-muted-foreground">
                    Describe a trip to start planning. Follow-ups in the same chat (e.g. &quot;make it a week
                    instead&quot;) reference what you asked before.
                  </p>
                )}

                <div className="flex flex-col gap-4">
                  {messages.map((msg) => (
                    <ChatMessage key={msg.id} message={msg} />
                  ))}
                  {pending.kind === "submitting" && (
                    <>
                      <ChatMessage
                        message={{ id: -1, role: "user", content: pending.prompt, trip: null, created_at: "" }}
                      />
                      <PendingIndicator />
                    </>
                  )}
                </div>
              </>
            )}
          </div>

          {/* Locked to the bottom -- shrink-0 for the same reason the header is. */}
          <div className="shrink-0 pt-2 pb-6">
            {error && (
              <Alert variant="destructive" className="mb-2">
                <AlertDescription className="flex items-center justify-between gap-3">
                  <span>{error.message}</span>
                  <Button variant="outline" size="sm" className="shrink-0" onClick={error.retry}>
                    Try again
                  </Button>
                </AlertDescription>
              </Alert>
            )}

            <ChatInput disabled={pending.kind !== "idle"} onSubmit={handleSubmit} />
          </div>
        </main>

        {children}
      </div>
    </ChatShellContext.Provider>
  );
}
