"use client";

import { Plus, Trash2 } from "lucide-react";
import type { ConversationSummary } from "@/lib/types";
import { signOutAction } from "@/lib/authActions";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";

interface SidebarProps {
  conversations: ConversationSummary[];
  activeConversationId: number | null;
  onSelect: (id: number) => void;
  onNewChat: () => void;
  onDelete: (id: number) => void;
  userEmail: string | null;
}

export default function Sidebar({
  conversations,
  activeConversationId,
  onSelect,
  onNewChat,
  onDelete,
  userEmail,
}: SidebarProps) {
  return (
    <aside className="flex w-full shrink-0 flex-col gap-3 border-b bg-muted/30 p-4 md:w-64 md:border-r md:border-b-0">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold">
        <span aria-hidden>🧭</span> Itinera
      </h3>
      <Button onClick={onNewChat} className="justify-center gap-1.5">
        <Plus className="size-4" />
        New chat
      </Button>

      <p className="mt-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">Chats</p>
      {conversations.length === 0 && (
        <p className="text-sm text-muted-foreground">No chats yet — start one below.</p>
      )}

      <ScrollArea className="-mx-1 max-h-48 flex-1 px-1 md:max-h-none">
        <ul className="flex flex-col gap-1">
          {conversations.map((conv) => {
            const active = conv.id === activeConversationId;
            return (
              <li key={conv.id} className="flex items-center gap-1">
                <button
                  onClick={() => onSelect(conv.id)}
                  className={`flex-1 truncate rounded-md px-2.5 py-1.5 text-left text-sm transition-colors ${
                    active ? "bg-primary text-primary-foreground" : "hover:bg-muted"
                  }`}
                >
                  {conv.title || "New chat"}
                </button>
                <button
                  onClick={() => onDelete(conv.id)}
                  title="Delete this chat"
                  aria-label={`Delete ${conv.title}`}
                  className="shrink-0 rounded-md p-1.5 text-muted-foreground opacity-60 transition-opacity hover:text-destructive hover:opacity-100"
                >
                  <Trash2 className="size-3.5" />
                </button>
              </li>
            );
          })}
        </ul>
      </ScrollArea>

      {userEmail && (
        <>
          <Separator />
          <div className="flex flex-col gap-1.5">
            <span className="truncate text-xs text-muted-foreground" title={userEmail}>
              {userEmail}
            </span>
            <Button variant="outline" size="sm" onClick={() => signOutAction()}>
              Sign out
            </Button>
          </div>
        </>
      )}
    </aside>
  );
}
