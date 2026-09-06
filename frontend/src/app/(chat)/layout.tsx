import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { listConversations } from "@/lib/backend";
import ChatShell from "@/components/ChatShell";

// Shared by "/" (page.tsx) and "/trips/[tripId]" (trips/[tripId]/page.tsx)
// via this (chat) route group -- the parenthesized segment doesn't appear
// in the URL, so those routes are unaffected. The whole point of this
// layout existing: Next.js's App Router does NOT remount a layout when
// navigating between sibling routes that share it, only the page segment
// that actually changed. Previously "/" and "/trips/[tripId]" were both
// direct children of the bare root layout with no shared layout between
// them, so every switch between them fully remounted the entire chat UI
// (sidebar included) and re-ran this auth check + conversation-list fetch
// from scratch -- see decisions.md's chat-shell restructure entry for the
// full diagnosis (a Network-tab capture showing paired duplicate fetches,
// plus confirmation this auth+fetch work was being redundantly repeated on
// every navigation between the two routes).
//
// One real behavior change from moving this here: this auth check now
// only re-runs on first entry into the group or a hard reload, not on
// every navigation between "/" and "/trips/[tripId]" the way each page's
// own auth() call used to. Given the JWT session strategy (auth.ts) this
// is an acceptable trade -- a session invalidated mid-visit is now caught
// on next entry/reload rather than instantly, not never.
export default async function ChatLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }

  const conversations = await listConversations();

  return (
    <ChatShell initialConversations={conversations} userEmail={session.user.email ?? null}>
      {children}
    </ChatShell>
  );
}
