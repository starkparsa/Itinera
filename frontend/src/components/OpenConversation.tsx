"use client";

import { useEffect } from "react";
import type { ConversationDetail } from "@/lib/types";
import { useChatShellContext } from "./ChatShell";

// Invisible bridge between a server-rendered page (which knows, from its
// own route params/searchParams, which conversation should be open) and
// the persistent ChatShell (which lives one level up, in
// app/(chat)/layout.tsx, and doesn't re-render per navigation the way a
// page does). Each page under app/(chat)/ renders one of these with the id
// it resolved server-side; on mount, it tells the shell to open it.
//
// `initialDetail`, when the page already fetched it server-side (see e.g.
// trips/[tripId]/page.tsx calling getConversation() alongside getTrip()),
// lets the shell apply it directly with no further network call --
// otherwise the shell would fetch it again itself, client-side, after this
// component mounts: a second slow round trip stacked right after the
// page's own navigation, which is what made switching chats feel like it
// was "double loading."
//
// Runs once per mount only -- a real route change to a *different*
// conversation is a new mount of the page (and this bridge) with a new
// `id`, not a prop update on the same instance, so a plain mount effect is
// the right shape here, same as ChatApp.tsx's earlier "runs once on mount"
// effect this replaces.
export default function OpenConversation({
  id,
  initialDetail,
}: {
  id: number | null;
  initialDetail?: ConversationDetail | null;
}) {
  const { openConversation, seedConversation } = useChatShellContext();

  useEffect(() => {
    if (id != null && initialDetail) {
      seedConversation(id, initialDetail);
    } else {
      openConversation(id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}
