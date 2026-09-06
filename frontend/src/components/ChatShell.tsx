"use client";

import { createContext, useContext, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Menu, Luggage } from "lucide-react";
import type { ConversationDetail, ConversationSummary, MessageOut, TripResponse } from "@/lib/types";
import { deleteConversation, listConversations } from "@/lib/backend";
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
import { useSidebarOpen } from "@/hooks/use-sidebar-open";
import { useScrollRestore } from "@/hooks/use-scroll-restore";
import { useConversationLoader } from "@/hooks/use-conversation-loader";

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
  // See useConversationLoader's own docstring for the cache/generation-
  // counter/pending-error rationale (extracted 2026-09 maintainability
  // review).
  const {
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
  } = useConversationLoader();
  // Collapsed by default -- "nothing extra on screen until asked for it,"
  // per the Trip Hub v2 direction (decisions.md's UI styling entry). Same
  // boolean drives both presentations below (inline column on desktop, an
  // overlay Sheet on mobile) -- there's one open/closed concept, just two
  // ways of rendering it depending on viewport.
  //
  // Persisted to localStorage as a secondary safety net (e.g. a hard
  // refresh) -- now that this shell lives in a shared layout instead of
  // being remounted per page, the toggle already survives normal
  // navigation between "/" and "/trips/[tripId]" on its own. See
  // useSidebarOpen's own docstring for the useSyncExternalStore/override
  // precedence rationale (extracted 2026-09 maintainability review).
  const [sidebarOpen, setSidebarOpen] = useSidebarOpen();
  // Real breakpoint check (not just a CSS class) -- deciding which of the
  // two presentations to *mount* has to happen in JS. A CSS-only "hide the
  // Sheet at md:" would still leave Base UI's Dialog open and trapping
  // focus/scroll-locking the page behind an invisible overlay on desktop.
  const isMobile = useIsMobile();
  const router = useRouter();
  const pathname = usePathname();

  // See useScrollRestore's own docstring for the restore/jump-to-bottom
  // logic (extracted 2026-09 maintainability review).
  const { messageLogRef, handleMessageLogScroll, invalidateScrollPosition } = useScrollRestore(
    activeConversationId,
    messages,
    pending.kind,
  );

  async function refreshConversationList() {
    setConversations(await listConversations());
  }

  async function handleDelete(id: number) {
    await deleteConversation(id);
    invalidateConversation(id);
    invalidateScrollPosition(id);
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

  function handleSubmit(prompt: string) {
    return submitPrompt(prompt, refreshConversationList);
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
